using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text.Json;
using Rhino;
using Rhino.DocObjects;
using Rhino.Geometry;

namespace SidaRhino
{
    /// <summary>
    /// A diagram's drawing instruction (docs/rhino-api.md, "다이어그램") as real geometry: slabs as
    /// solids, fills as solid hatches, lines as polylines, words as text, on a sublayer of
    /// "Sida 다이어그램", grouped so the diagram moves as one. Sida decided what is drawn and where
    /// within the drawing; here it is only made, and set down beside the model.
    ///
    /// Drawing a kind again replaces what was drawn of it before, where it stood. What the
    /// designer has moved or reshaped since is theirs and stays (as with SidaPull).
    /// </summary>
    public static class Drawer
    {
        public const string ParentLayer = "Sida 다이어그램";
        public const string KindKey = "sida.diagram";
        private static readonly System.Drawing.Color Ink = System.Drawing.Color.FromArgb(32, 38, 45);

        /// <returns>How many objects were made.</returns>
        public static int Draw(RhinoDoc doc, JsonElement drawing)
        {
            var kind = drawing.GetProperty("kind").GetString() ?? "";
            var title = drawing.GetProperty("title").GetString() ?? kind;
            var toDoc = RhinoMath.UnitScale(UnitSystem.Meters, doc.ModelUnitSystem);
            var tolerance = doc.ModelAbsoluteTolerance;
            var bounds = drawing.GetProperty("bounds").EnumerateArray().Select(v => v.GetDouble() * toDoc).ToArray();

            // What was drawn of this kind before goes; what the designer changed since is theirs.
            foreach (var obj in doc.Objects.Where(o => o.Attributes.GetUserString(KindKey) == kind).ToList())
            {
                if (obj.Attributes.GetUserString(Importer.StampKey) == Importer.Stamp(obj.Geometry))
                {
                    doc.Objects.Delete(obj, true);
                    continue;
                }
                obj.Attributes.DeleteUserString(KindKey);
                obj.Attributes.DeleteUserString(Importer.StampKey);
                obj.CommitChanges();
            }

            var corner = Corner(doc, kind);
            var move = new Vector3d(corner.X - bounds[0], corner.Y - bounds[1], 0);
            var layer = Layer(doc, title);
            var made = new List<Guid>();

            Point3d at(double x, double y, double z) => new Point3d(x * toDoc, y * toDoc, z * toDoc) + move;
            List<Curve> loops(JsonElement rings, double z)
            {
                var curves = new List<Curve>();
                foreach (var ring in rings.EnumerateArray())
                {
                    var points = ring.EnumerateArray().Select(p => at(p[0].GetDouble(), p[1].GetDouble(), z)).ToList();
                    if (points.Count < 3)
                        continue;
                    points.Add(points[0]);
                    curves.Add(new PolylineCurve(points));
                }
                return curves;
            }
            void add(GeometryBase? geometry, System.Drawing.Color color, Action<ObjectAttributes>? more = null)
            {
                if (geometry == null)
                    return;
                var attributes = new ObjectAttributes { LayerIndex = layer, Name = title, ColorSource = ObjectColorSource.ColorFromObject, ObjectColor = color };
                more?.Invoke(attributes);
                attributes.SetUserString(KindKey, kind);
                attributes.SetUserString(Importer.StampKey, Importer.Stamp(geometry));
                var id = doc.Objects.Add(geometry, attributes);
                if (id != Guid.Empty)
                    made.Add(id);
            }

            foreach (var item in drawing.GetProperty("items").EnumerateArray())
            {
                var type = item.GetProperty("type").GetString();
                if (type == "slab")
                {
                    var z = item.GetProperty("z").GetDouble();
                    var height = item.GetProperty("height").GetDouble() * toDoc;
                    var color = Colour(item.GetProperty("color").GetString());
                    foreach (var flat in Brep.CreatePlanarBreps(loops(item.GetProperty("rings"), z), tolerance) ?? Array.Empty<Brep>())
                    {
                        var path = new LineCurve(Point3d.Origin, new Point3d(0, 0, height));
                        add(flat.Faces.Count > 0 ? flat.Faces[0].CreateExtrusion(path, true) ?? flat : flat, color);
                    }
                }
                else if (type == "fill")
                {
                    var color = Colour(item.GetProperty("color").GetString());
                    if (item.TryGetProperty("light", out var light) && light.ValueKind == JsonValueKind.True)
                        color = System.Drawing.Color.FromArgb((color.R + 255) / 2, (color.G + 255) / 2, (color.B + 255) / 2);
                    var curves = loops(item.GetProperty("rings"), item.GetProperty("z").GetDouble());
                    var hatches = Hatch.Create(curves, Solid(doc), 0, 1, tolerance);
                    if (hatches != null && hatches.Length > 0)
                    {
                        foreach (var hatch in hatches)
                            add(hatch, color);
                    }
                    else
                    {
                        foreach (var flat in Brep.CreatePlanarBreps(curves, tolerance) ?? Array.Empty<Brep>())
                            add(flat, color);
                    }
                }
                else if (type == "line")
                {
                    var points = item.GetProperty("points").EnumerateArray().Select(p => at(p[0].GetDouble(), p[1].GetDouble(), p[2].GetDouble())).ToList();
                    if (points.Count < 2)
                        continue;
                    if (item.GetProperty("closed").GetBoolean())
                        points.Add(points[0]);
                    var bold = item.GetProperty("bold").GetBoolean();
                    var dashed = item.GetProperty("dashed").GetBoolean();
                    add(new PolylineCurve(points), Colour(item.GetProperty("color").GetString()), attributes =>
                    {
                        if (bold)
                        {
                            attributes.PlotWeightSource = ObjectPlotWeightSource.PlotWeightFromObject;
                            attributes.PlotWeight = 0.5;
                        }
                        var linetype = dashed ? doc.Linetypes.FindName("Dashed") : null;
                        if (linetype != null)
                        {
                            attributes.LinetypeSource = ObjectLinetypeSource.LinetypeFromObject;
                            attributes.LinetypeIndex = linetype.Index;
                        }
                    });
                }
                else if (type == "text")
                {
                    var p = item.GetProperty("at");
                    var origin = at(p[0].GetDouble(), p[1].GetDouble(), p[2].GetDouble());
                    var upright = item.GetProperty("upright").GetBoolean();  // stands facing south, beside an axonometric
                    var plane = new Plane(origin, Vector3d.XAxis, upright ? Vector3d.ZAxis : Vector3d.YAxis);
                    var text = TextEntity.Create(item.GetProperty("text").GetString() ?? "", plane, doc.DimStyles.Current, false, 0, 0);
                    if (text == null)
                        continue;
                    text.DimensionScale = 1;  // the letter height below is the height in the model
                    text.TextHeight = item.GetProperty("size").GetDouble() * toDoc;
                    text.Justification = item.GetProperty("anchor").GetString() switch
                    {
                        "middle" => TextJustification.BottomCenter,
                        "end" => TextJustification.BottomRight,
                        _ => TextJustification.BottomLeft,
                    };
                    add(text, Ink);
                }
            }
            if (made.Count > 1)
                doc.Groups.Add(title, made);
            return made.Count;
        }

        /// <summary>
        /// Where a drawing's lower left corner goes: where this kind stood before, else east of
        /// everything in the document (the model and the diagrams already drawn), on the line of
        /// the model's south edge.
        /// </summary>
        private static Point3d Corner(RhinoDoc doc, string kind)
        {
            var key = $"{KindKey}.{kind}.at";
            var kept = (doc.Strings.GetValue(key) ?? "").Split(',');
            if (kept.Length == 2 && double.TryParse(kept[0], NumberStyles.Float, CultureInfo.InvariantCulture, out var x)
                && double.TryParse(kept[1], NumberStyles.Float, CultureInfo.InvariantCulture, out var y))
                return new Point3d(x, y, 0);
            var all = BoundingBox.Empty;
            var model = BoundingBox.Empty;
            var settings = new ObjectEnumeratorSettings { ActiveObjects = true, HiddenObjects = false, DeletedObjects = false, LockedObjects = true };
            foreach (var obj in doc.Objects.GetObjectList(settings))
            {
                var box = obj.Geometry.GetBoundingBox(false);
                if (!box.IsValid)
                    continue;
                all.Union(box);
                if (string.IsNullOrEmpty(obj.Attributes.GetUserString(KindKey)))
                    model.Union(box);
            }
            var metre = RhinoMath.UnitScale(UnitSystem.Meters, doc.ModelUnitSystem);
            var corner = all.IsValid
                ? new Point3d(all.Max.X + Math.Max(10 * metre, (all.Max.X - all.Min.X) * 0.08), model.IsValid ? model.Min.Y : all.Min.Y, 0)
                : Point3d.Origin;
            doc.Strings.SetString(key, string.Format(CultureInfo.InvariantCulture, "{0:0.###},{1:0.###}", corner.X, corner.Y));
            return corner;
        }

        /// <summary>The diagram's own sublayer; diagram layers mean "ignore", so a drawing never counts as a building.</summary>
        private static int Layer(RhinoDoc doc, string title)
        {
            var parent = doc.Layers.FindByFullPath(ParentLayer, -1);
            if (parent < 0)
            {
                parent = doc.Layers.Add(new Layer { Name = ParentLayer });
                Meanings.Set(doc, parent, "ignore", null);
            }
            var index = doc.Layers.FindByFullPath(ParentLayer + "::" + title, -1);
            if (index < 0)
            {
                index = doc.Layers.Add(new Layer { Name = title, ParentLayerId = doc.Layers.FindIndex(parent).Id });
                Meanings.Set(doc, index, "ignore", null);
            }
            return index;
        }

        private static int Solid(RhinoDoc doc)
        {
            var pattern = doc.HatchPatterns.FindName("Solid");
            return pattern != null ? pattern.Index : doc.HatchPatterns.Add(HatchPattern.Defaults.Solid);
        }

        private static System.Drawing.Color Colour(string? hex)
        {
            if (hex != null && hex.Length == 7 && hex[0] == '#'
                && int.TryParse(hex.Substring(1), NumberStyles.HexNumber, CultureInfo.InvariantCulture, out var rgb))
                return System.Drawing.Color.FromArgb((rgb >> 16) & 255, (rgb >> 8) & 255, rgb & 255);
            return Ink;
        }
    }
}
