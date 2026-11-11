using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Rhino;
using Rhino.DocObjects;
using Rhino.FileIO;
using Rhino.Geometry;

namespace SidaRhino
{
    /// <summary>
    /// The drafting table (Sida's 3dm export, in metres) into this document: its layers are made
    /// under a "Sida" parent layer, objects that came from Sida before (user string sida.id) are
    /// replaced, and the designer's own objects are never touched. An object from Sida that the
    /// designer has since moved or reshaped is theirs: it is kept (its id moves to sida.from)
    /// and only what still stands as Sida sent it is replaced. The export's coordinates are kept
    /// (scaled to the document's units), so a push goes back in the same frame.
    /// </summary>
    public static class Importer
    {
        public const string ParentLayer = "Sida";
        public const string IdKey = "sida.id";
        public const string FromKey = "sida.from";    // the id an object had before the designer changed it
        public const string StampKey = "sida.stamp";  // the object's extent as Sida sent it

        /// <summary>What Sida's own layers mean, by the kind of thing on them; a mass has no meaning until the designer gives one.</summary>
        private static readonly Dictionary<string, string> MeaningOfKind = new Dictionary<string, string>
        {
            ["context"] = "surroundings", ["site"] = "site", ["origin"] = "ignore", ["tracing"] = "ignore",
        };

        /// <summary>How many objects of the last import were kept because the designer had changed them.</summary>
        public static int KeptLast { get; private set; }

        public static int Import(RhinoDoc doc, byte[] bytes)
        {
            var path = Path.Combine(Path.GetTempPath(), $"sida-{Guid.NewGuid():N}.3dm");
            File.WriteAllBytes(path, bytes);
            try
            {
                using var file = File3dm.Read(path);
                if (file == null)
                    throw new SidaException("Sida가 보낸 3dm 파일을 읽지 못했습니다.");
                return Import(doc, file);
            }
            finally
            {
                try { File.Delete(path); } catch (IOException) { }
            }
        }

        private static int Import(RhinoDoc doc, File3dm file)
        {
            var scale = RhinoMath.UnitScale(UnitSystem.Meters, doc.ModelUnitSystem);
            var transform = Transform.Scale(Point3d.Origin, scale);

            // What Sida put here before goes, so a block moved on the table moves here too. What
            // the designer changed since stays and becomes theirs.
            var old = new List<RhinoObject>();
            var kept = new List<RhinoObject>();
            foreach (var obj in doc.Objects)
            {
                var id = obj.Attributes.GetUserString(IdKey);
                if (string.IsNullOrEmpty(id))
                    continue;
                var stamp = obj.Attributes.GetUserString(StampKey);
                if (!string.IsNullOrEmpty(stamp) && stamp != Stamp(obj.Geometry))
                    kept.Add(obj);
                else
                    old.Add(obj);
            }
            foreach (var obj in kept)
            {
                obj.Attributes.SetUserString(FromKey, obj.Attributes.GetUserString(IdKey));
                obj.Attributes.DeleteUserString(IdKey);
                obj.Attributes.DeleteUserString(StampKey);
                obj.CommitChanges();
            }
            foreach (var obj in old)
                doc.Objects.Delete(obj, true);
            KeptLast = kept.Count;

            var parentIndex = doc.Layers.FindByFullPath(ParentLayer, -1);
            if (parentIndex < 0)
                parentIndex = doc.Layers.Add(new Layer { Name = ParentLayer });
            var parentId = doc.Layers.FindIndex(parentIndex).Id;

            var byId = new Dictionary<Guid, Layer>();
            foreach (var layer in file.AllLayers)
                byId[layer.Id] = layer;
            var layerIndex = new Dictionary<int, int>();  // file layer index → document layer index
            foreach (var layer in file.AllLayers)  // parents come before their sublayers in the export
            {
                var fullPath = ParentLayer + "::" + FullPathOf(byId, layer);
                var index = doc.Layers.FindByFullPath(fullPath, -1);
                if (index < 0)
                {
                    var parent = parentId;
                    if (layer.ParentLayerId != Guid.Empty && byId.TryGetValue(layer.ParentLayerId, out var above))
                    {
                        var aboveIndex = doc.Layers.FindByFullPath(ParentLayer + "::" + FullPathOf(byId, above), -1);
                        if (aboveIndex >= 0)
                            parent = doc.Layers.FindIndex(aboveIndex).Id;
                    }
                    index = doc.Layers.Add(new Layer { Name = layer.Name, ParentLayerId = parent, Color = layer.Color, IsVisible = layer.IsVisible });
                }
                layerIndex[layer.Index] = index;
            }

            var count = 0;
            var kinds = new Dictionary<int, HashSet<string>>();  // document layer index → kinds put on it
            foreach (var item in file.Objects)
            {
                var geometry = item.Geometry?.Duplicate();
                if (geometry == null)
                    continue;
                geometry.Transform(transform);
                var attributes = new ObjectAttributes
                {
                    LayerIndex = layerIndex.TryGetValue(item.Attributes.LayerIndex, out var index) ? index : parentIndex,
                    Name = item.Attributes.Name,
                };
                var keys = item.Attributes.GetUserStrings();
                foreach (string? key in keys.AllKeys)
                    if (key != null)
                        attributes.SetUserString(key, keys[key]);
                if (!string.IsNullOrEmpty(attributes.GetUserString(IdKey)))
                    attributes.SetUserString(StampKey, Stamp(geometry));
                if (doc.Objects.Add(geometry, attributes) != Guid.Empty)
                    count++;
                if (!kinds.TryGetValue(attributes.LayerIndex, out var onLayer))
                    kinds[attributes.LayerIndex] = onLayer = new HashSet<string>();
                onLayer.Add(attributes.GetUserString("sida.kind") ?? "");
                if (attributes.GetUserString("sida.kind") == "origin")
                {
                    doc.Strings.SetString("sida.origin", attributes.GetUserString("sida.origin") ?? "");
                    var project = attributes.GetUserString("sida.project");
                    if (!string.IsNullOrEmpty(project))
                        Meanings.SetProject(doc, project!);
                }
            }
            // Sida knows what its own layers are (the surroundings, the site boundary), so those
            // get their meaning here; a layer the designer already gave a meaning keeps it.
            foreach (var (index, onLayer) in kinds)
            {
                var layer = doc.Layers.FindIndex(index);
                if (layer == null || onLayer.Count != 1 || !string.IsNullOrEmpty(Meanings.MeaningOf(layer)))
                    continue;
                if (MeaningOfKind.TryGetValue(onLayer.First(), out var meaning))
                    Meanings.Set(doc, index, meaning, Meanings.FloorHeightOf(layer));
            }
            doc.Views.Redraw();
            return count;
        }

        /// <summary>
        /// An object's extent to the millimetre in its own units: equal as long as it stands as
        /// Sida sent it, different once the designer moves or reshapes it.
        /// </summary>
        private static string Stamp(GeometryBase geometry)
        {
            var box = geometry.GetBoundingBox(true);
            if (!box.IsValid)
                return "";
            string n(double value) => Math.Round(value, 3).ToString("0.###", System.Globalization.CultureInfo.InvariantCulture);
            return $"{n(box.Min.X)},{n(box.Min.Y)},{n(box.Min.Z)},{n(box.Max.X)},{n(box.Max.Y)},{n(box.Max.Z)}";
        }

        /// <summary>"매스::안 A" for a file layer, from its parents (a file layer's own FullPath may not resolve them).</summary>
        private static string FullPathOf(Dictionary<Guid, Layer> byId, Layer layer)
        {
            var path = layer.Name;
            var at = layer;
            while (at.ParentLayerId != Guid.Empty && byId.TryGetValue(at.ParentLayerId, out var above))
            {
                path = above.Name + "::" + path;
                at = above;
            }
            return path;
        }
    }
}
