using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Imaging;
using System.Globalization;
using System.IO;
using System.Linq;
using Rhino;
using Rhino.Display;
using Rhino.DocObjects;
using Rhino.Geometry;

namespace SidaRhino
{
    /// <summary>
    /// The document as a snapshot (docs/rhino-api.md, schema 1): what Rhino itself measured for
    /// the visible bodies (polysurfaces, extrusions, surfaces, SubDs, meshes), in metres, plus
    /// view captures. Only measuring happens here; whether a figure counts and what the ratios
    /// are is Sida's.
    ///
    /// How much is measured follows the layer's meaning: a body on a layer that means building
    /// is cut (footprint and a section at every floor height), one on a context layer only gets
    /// its extent, and one on a layer without a meaning is only named, so Sida can say how many
    /// are left out.
    ///
    /// v1 limits, by design: the footprint is the section 5 cm above the object's lowest point
    /// (not the projection of overhangs); floors are sections every floor height of the layer,
    /// so a layer without a floor height gives no floor areas; blocks (instances) are not
    /// opened; the captures are the plan and perspective views as they are.
    /// </summary>
    public static class SnapshotBuilder
    {
        public const int MaxMeshVertices = 20000;
        public const int MaxOutline = 500;  // points in one ring (snapshot.py MAX_OUTLINE)
        public const int MaxRings = 50;     // rings in one footprint (snapshot.py MAX_RINGS)
        public const int MaxFloors = 200;   // snapshot.py MAX_FLOORS
        private const double SectionLift = 0.05;  // metres above a floor level, so a box gives one clean section

        /// <param name="built">The meaning codes Sida counts as building (from /api/rhino/hello).</param>
        public static Dictionary<string, object?> Build(RhinoDoc doc, ICollection<string> built, bool withMeshes)
        {
            var toMetres = RhinoMath.UnitScale(doc.ModelUnitSystem, UnitSystem.Meters);
            var layers = new List<object>();
            var meaningByIndex = new Dictionary<int, (string Meaning, double? FloorHeight)>();
            foreach (var (layer, meaning, floorHeight) in Meanings.All(doc))
            {
                meaningByIndex[layer.Index] = (meaning, floorHeight);
                layers.Add(new Dictionary<string, object?>
                {
                    ["path"] = layer.FullPath,
                    ["meaning"] = meaning,
                    ["color"] = $"#{layer.Color.R:x2}{layer.Color.G:x2}{layer.Color.B:x2}",
                    ["floor_height"] = floorHeight.HasValue ? Math.Round(floorHeight.Value * toMetres, 3) : null,
                });
            }

            var objects = new List<object>();
            var settings = new ObjectEnumeratorSettings
            {
                ActiveObjects = true, HiddenObjects = false, DeletedObjects = false, VisibleFilter = true, LockedObjects = true,
            };
            foreach (var obj in doc.Objects.GetObjectList(settings))
            {
                var layer = doc.Layers.FindIndex(obj.Attributes.LayerIndex);
                if (layer == null || !layer.IsVisible)
                    continue;
                meaningByIndex.TryGetValue(obj.Attributes.LayerIndex, out var meant);
                var meaning = meant.Meaning ?? "";
                var measured = Measure(
                    obj.Geometry, toMetres,
                    cut: built.Contains(meaning),
                    floorHeight: meant.FloorHeight,  // document units
                    withMesh: withMeshes && meaning.Length > 0);
                if (measured == null)
                    continue;
                measured["id"] = obj.Id.ToString();
                measured["sida_id"] = obj.Attributes.GetUserString(Importer.IdKey) ?? obj.Attributes.GetUserString(Importer.FromKey);
                measured["layer"] = layer.FullPath;
                measured["name"] = obj.Name ?? "";
                objects.Add(measured);
            }

            var snapshot = new Dictionary<string, object?>
            {
                ["schema"] = SidaClient.Schema,
                ["rhino"] = new Dictionary<string, object?>
                {
                    ["version"] = RhinoApp.Version.ToString(),
                    ["file"] = string.IsNullOrEmpty(doc.Name) ? "" : doc.Name,
                    ["units"] = "m",
                },
                ["layers"] = layers,
                ["objects"] = objects,
                ["views"] = new List<object>(),
            };
            var origin = doc.Strings.GetValue("sida.origin");
            if (!string.IsNullOrEmpty(origin))
            {
                var parts = origin.Split(',');
                if (parts.Length == 2 && double.TryParse(parts[0], NumberStyles.Float, CultureInfo.InvariantCulture, out var lon)
                    && double.TryParse(parts[1], NumberStyles.Float, CultureInfo.InvariantCulture, out var lat))
                    snapshot["origin"] = new Dictionary<string, object?> { ["lon"] = lon, ["lat"] = lat, ["matches_project"] = true };
            }
            return snapshot;
        }

        /// <summary>
        /// One body in metres; null for geometry that has no body (curves, points, text, blocks).
        /// With <paramref name="cut"/> it is measured whole: volume, footprint, a section at
        /// every floor height. Without, only its base and height are read.
        /// </summary>
        private static Dictionary<string, object?>? Measure(GeometryBase geometry, double toMetres, bool cut, double? floorHeight, bool withMesh)
        {
            Brep? brep = geometry switch
            {
                Brep b => b,
                Extrusion e => e.ToBrep(true),
                Surface s => s.ToBrep(),
                SubD d => d.ToBrep(new SubDToBrepOptions()),
                _ => null,
            };
            Mesh? mesh = geometry as Mesh;
            if (brep == null && mesh == null)
                return null;
            var box = geometry.GetBoundingBox(true);
            if (!box.IsValid)
                return null;

            var item = new Dictionary<string, object?>
            {
                ["volume"] = null,
                ["height"] = Math.Round((box.Max.Z - box.Min.Z) * toMetres, 3),
                ["base"] = Math.Round(box.Min.Z * toMetres, 3),
                ["footprint"] = null,
                ["floors"] = new List<object>(),
            };
            if (cut)
            {
                double? volume = null;
                if (brep != null && brep.IsSolid)
                    volume = VolumeMassProperties.Compute(brep)?.Volume;
                else if (mesh != null && mesh.IsClosed)
                    volume = VolumeMassProperties.Compute(mesh)?.Volume;
                if (volume.HasValue)
                    item["volume"] = Math.Round(Math.Abs(volume.Value) * toMetres * toMetres * toMetres, 3);

                var lift = SectionLift / toMetres;
                var ground = Section(brep, mesh, box.Min.Z + lift, toMetres);
                item["footprint"] = ground?.Rings;
                if (ground != null && floorHeight.HasValue && floorHeight.Value > 0)
                {
                    var floors = (List<object>)item["floors"]!;
                    for (var level = box.Min.Z; level + lift < box.Max.Z && floors.Count < MaxFloors; level += floorHeight.Value)
                    {
                        var section = floors.Count == 0 ? ground : Section(brep, mesh, level + lift, toMetres);
                        if (section == null || section.AreaM2 <= 0)
                            break;
                        floors.Add(new Dictionary<string, object?> { ["z"] = Math.Round(level * toMetres, 3), ["area"] = Math.Round(section.AreaM2, 3) });
                    }
                }
            }
            if (withMesh)
            {
                var small = SmallMesh(brep, mesh, toMetres);
                if (small != null)
                    item["mesh"] = small;
            }
            return item;
        }

        /// <summary>A horizontal cut: its closed curves as rings of [x, y] metres (null when one cannot be drawn), and the area inside them.</summary>
        private sealed record Cut(List<List<List<double>>>? Rings, double AreaM2);

        /// <summary>
        /// The body cut at height z (document units). A closed curve inside another is a hole (a
        /// courtyard), so the area is counted by how deep each curve is nested. Null when the cut
        /// has no closed curve (an open body, or nothing at that height).
        /// </summary>
        private static Cut? Section(Brep? brep, Mesh? mesh, double z, double toMetres)
        {
            var plane = new Plane(new Point3d(0, 0, z), Vector3d.ZAxis);
            var tolerance = 0.001 / toMetres;  // 1 mm
            Curve[]? pieces = brep != null ? Brep.CreateContourCurves(brep, plane)
                : mesh != null ? Mesh.CreateContourCurves(mesh, plane, tolerance) : null;
            if (pieces == null || pieces.Length == 0)
                return null;
            var joined = Curve.JoinCurves(pieces, tolerance) ?? pieces;
            var closed = joined.Where(c => c != null && c.IsClosed).ToList();
            if (closed.Count == 0)
                return null;

            double area = 0;
            var rings = new List<List<List<double>>>();
            var drawn = true;
            for (var i = 0; i < closed.Count; i++)
            {
                var own = AreaMassProperties.Compute(closed[i])?.Area ?? 0;
                if (own <= 0)
                    continue;
                var depth = 0;
                for (var j = 0; j < closed.Count; j++)
                {
                    if (j != i && Curve.PlanarClosedCurveRelationship(closed[i], closed[j], plane, tolerance) == RegionContainment.AInsideB)
                        depth++;
                }
                area += depth % 2 == 0 ? own : -own;
                var ring = Ring(closed[i], toMetres);
                if (ring == null)
                    drawn = false;
                else
                    rings.Add(ring);
            }
            if (area <= 0)
                return null;
            return new Cut(drawn && rings.Count > 0 && rings.Count <= MaxRings ? rings : null, area * toMetres * toMetres);
        }

        /// <summary>
        /// A closed curve as [x, y] metres within the point limit: a polyline as it is, a curve
        /// to within 1 cm, then coarser until it fits. Null when it cannot be had.
        /// </summary>
        private static List<List<double>>? Ring(Curve curve, double toMetres)
        {
            Polyline? line = null;
            if (!(curve.TryGetPolyline(out line) && line.Count - 1 <= MaxOutline))
            {
                line = null;
                var tolerance = 0.01 / toMetres;
                var angle = 0.1;  // radians
                for (var attempt = 0; attempt < 5 && line == null; attempt++, tolerance *= 3, angle *= 2)
                {
                    var made = curve.ToPolyline(tolerance, angle, 0, 0)?.ToPolyline();
                    if (made != null && made.Count - 1 <= MaxOutline)
                        line = made;
                }
            }
            if (line == null || line.Count < 4)
                return null;
            var points = new List<List<double>>(line.Count - 1);
            for (var i = 0; i < line.Count - 1; i++)  // a closed polyline repeats its first point last
                points.Add(new List<double> { Math.Round(line[i].X * toMetres, 4), Math.Round(line[i].Y * toMetres, 4) });
            return points;
        }

        private static Dictionary<string, object?>? SmallMesh(Brep? brep, Mesh? mesh, double toMetres)
        {
            Mesh? joined = mesh;
            if (joined == null && brep != null)
            {
                var parts = Mesh.CreateFromBrep(brep, MeshingParameters.FastRenderMesh);
                if (parts == null || parts.Length == 0)
                    return null;
                joined = new Mesh();
                foreach (var part in parts)
                    joined.Append(part);
            }
            if (joined == null || joined.Vertices.Count == 0 || joined.Vertices.Count > MaxMeshVertices)
                return null;
            var v = new List<List<double>>(joined.Vertices.Count);
            foreach (var p in joined.Vertices)
                v.Add(new List<double> { Math.Round(p.X * toMetres, 3), Math.Round(p.Y * toMetres, 3), Math.Round(p.Z * toMetres, 3) });
            var f = new List<List<int>>(joined.Faces.Count);
            foreach (var face in joined.Faces)
                f.Add(face.IsQuad ? new List<int> { face.A, face.B, face.C, face.D } : new List<int> { face.A, face.B, face.C });
            return new Dictionary<string, object?> { ["v"] = v, ["f"] = f };
        }

        /// <summary>
        /// The plan view as plan.png and the perspective view as persp.png, declared in the
        /// snapshot. The views are found by name (Top, Perspective) and, where a view was renamed,
        /// by how they look: a parallel view straight down, a perspective view.
        /// </summary>
        public static Dictionary<string, byte[]> Capture(RhinoDoc doc, Dictionary<string, object?> snapshot, int width = 1200, int height = 900)
        {
            var views = new Dictionary<string, byte[]>();
            var declared = (List<object>)snapshot["views"]!;
            var all = doc.Views.GetViewList(ViewTypeFilter.Model);
            var plan = doc.Views.Find("Top", false)
                ?? all.FirstOrDefault(v => v.ActiveViewport.IsParallelProjection && v.ActiveViewport.CameraDirection.IsParallelTo(Vector3d.ZAxis, 0.01) == -1);
            var persp = doc.Views.Find("Perspective", false) ?? all.FirstOrDefault(v => v.ActiveViewport.IsPerspectiveProjection);
            foreach (var (view, kind, file) in new[] { (plan, "plan", "plan.png"), (persp, "persp", "persp.png") })
            {
                if (view == null)
                    continue;
                using var bitmap = view.CaptureToBitmap(new Size(width, height));
                if (bitmap == null)
                    continue;
                using var stream = new MemoryStream();
                bitmap.Save(stream, ImageFormat.Png);
                views[file] = stream.ToArray();
                declared.Add(new Dictionary<string, object?> { ["kind"] = kind, ["file"] = file });
            }
            return views;
        }
    }
}
