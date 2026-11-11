using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Linq;
using Rhino;
using Rhino.DocObjects;
using Rhino.Geometry;

namespace SidaRhino
{
    /// <summary>
    /// The document as a snapshot (docs/rhino-api.md, schema 1): what Rhino itself measured for
    /// every visible object on a layer with a meaning, in metres, plus view captures. Only
    /// measuring happens here; whether a figure counts and what the ratios are is Sida's.
    ///
    /// v1 limits, by design: the footprint is the section 5 cm above the object's lowest point
    /// (not the projection of overhangs); floors are sections every floor height of the layer,
    /// so a layer without a floor height gives no floor areas (the object is then unmeasured
    /// in Sida); the captures are the Top and Perspective views as they are.
    /// </summary>
    public static class SnapshotBuilder
    {
        public const int MaxMeshVertices = 20000;
        private const double SectionLift = 0.05;  // metres above the lowest point, so a box gives one clean section

        public static Dictionary<string, object?> Build(RhinoDoc doc, bool withMeshes)
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
                if (!meaningByIndex.TryGetValue(obj.Attributes.LayerIndex, out var meant) || string.IsNullOrEmpty(meant.Meaning))
                    continue;  // a layer without a meaning is not sent: Sida counts them only by their layers
                var measured = Measure(obj.Geometry, toMetres, meant.FloorHeight * toMetres, withMeshes);
                if (measured == null)
                    continue;
                measured["id"] = obj.Id.ToString();
                measured["sida_id"] = obj.Attributes.GetUserString("sida.id");
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
                if (parts.Length == 2 && double.TryParse(parts[0], System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out var lon)
                    && double.TryParse(parts[1], System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out var lat))
                    snapshot["origin"] = new Dictionary<string, object?> { ["lon"] = lon, ["lat"] = lat, ["matches_project"] = true };
            }
            return snapshot;
        }

        /// <summary>Volume, height, footprint and floor areas of one object, in metres; null for geometry that has no body.</summary>
        private static Dictionary<string, object?>? Measure(GeometryBase geometry, double toMetres, double? floorHeight, bool withMesh)
        {
            Brep? brep = geometry switch
            {
                Brep b => b,
                Extrusion e => e.ToBrep(true),
                Surface s => s.ToBrep(),
                _ => null,
            };
            Mesh? mesh = geometry as Mesh;
            if (brep == null && mesh == null)
                return null;

            var box = geometry.GetBoundingBox(true);
            if (!box.IsValid)
                return null;
            double? volume = null;
            if (brep != null && brep.IsSolid)
                volume = VolumeMassProperties.Compute(brep)?.Volume;
            else if (mesh != null && mesh.IsClosed)
                volume = VolumeMassProperties.Compute(mesh)?.Volume;

            var floors = new List<object>();
            List<List<double>>? footprint = Section(brep, mesh, box.Min.Z + SectionLift / toMetres, toMetres, out var footprintArea);
            if (floorHeight.HasValue && floorHeight.Value > 0 && footprint != null)
            {
                var step = floorHeight.Value / toMetres;  // back to document units for the planes
                for (double z = box.Min.Z + SectionLift / toMetres; z < box.Max.Z; z += step)
                {
                    Section(brep, mesh, z, toMetres, out var area);
                    if (area <= 0)
                        break;
                    floors.Add(new Dictionary<string, object?> { ["z"] = Math.Round((z - SectionLift / toMetres) * toMetres, 3), ["area"] = Math.Round(area, 3) });
                }
            }

            var item = new Dictionary<string, object?>
            {
                ["volume"] = volume.HasValue ? Math.Round(volume.Value * toMetres * toMetres * toMetres, 3) : null,
                ["height"] = Math.Round((box.Max.Z - box.Min.Z) * toMetres, 3),
                ["footprint"] = footprint,
                ["floors"] = floors,
            };
            if (withMesh)
            {
                var small = SmallMesh(brep, mesh, toMetres);
                if (small != null)
                    item["mesh"] = small;
            }
            return item;
        }

        /// <summary>The largest closed section of the body at height z (document units) as [x, y] metres, and the area of all closed sections.</summary>
        private static List<List<double>>? Section(Brep? brep, Mesh? mesh, double z, double toMetres, out double areaM2)
        {
            areaM2 = 0;
            var plane = new Plane(new Point3d(0, 0, z), Vector3d.ZAxis);
            Curve[]? curves = brep != null ? Brep.CreateContourCurves(brep, plane) : mesh != null ? Mesh.CreateContourCurves(mesh, plane, 0.001 / toMetres) : null;
            if (curves == null)
                return null;
            Polyline? best = null;
            double bestArea = 0;
            foreach (var curve in curves)
            {
                if (curve == null || !curve.IsClosed)
                    continue;
                var area = AreaMassProperties.Compute(curve)?.Area ?? 0;
                areaM2 += area * toMetres * toMetres;
                var poly = curve.ToPolyline(0.01, 0.1, 0, 0)?.ToPolyline();
                if (poly != null && area > bestArea)
                {
                    best = poly;
                    bestArea = area;
                }
            }
            if (best == null)
                return null;
            var points = new List<List<double>>();
            for (var i = 0; i < best.Count - 1; i++)  // the polyline repeats its first point last
                points.Add(new List<double> { Math.Round(best[i].X * toMetres, 4), Math.Round(best[i].Y * toMetres, 4) });
            return points.Count >= 3 ? points : null;
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

        /// <summary>The Top view as plan.png and the Perspective view as persp.png (those that exist), declared in the snapshot.</summary>
        public static Dictionary<string, byte[]> Capture(RhinoDoc doc, Dictionary<string, object?> snapshot, int width = 1200, int height = 900)
        {
            var views = new Dictionary<string, byte[]>();
            var declared = (List<object>)snapshot["views"]!;
            foreach (var (viewName, kind, file) in new[] { ("Top", "plan", "plan.png"), ("Perspective", "persp", "persp.png") })
            {
                var view = doc.Views.Find(viewName, false);
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
