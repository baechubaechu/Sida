using System;
using System.Collections.Generic;
using System.IO;
using Rhino;
using Rhino.DocObjects;
using Rhino.FileIO;
using Rhino.Geometry;

namespace SidaRhino
{
    /// <summary>
    /// The drafting table (Sida's 3dm export, in metres) into this document: its layers are made
    /// under a "Sida" parent layer, objects that came from Sida before (user string sida.id) are
    /// replaced, and the designer's own objects are never touched. The export's coordinates are
    /// kept (scaled to the document's units), so a push goes back in the same frame.
    /// </summary>
    public static class Importer
    {
        public const string ParentLayer = "Sida";

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

            // What Sida put here before goes, so a block moved on the table moves here too.
            var old = new List<RhinoObject>();
            foreach (var obj in doc.Objects)
            {
                if (!string.IsNullOrEmpty(obj.Attributes.GetUserString("sida.id")))
                    old.Add(obj);
            }
            foreach (var obj in old)
                doc.Objects.Delete(obj, true);

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
                foreach (string key in keys.AllKeys)
                    attributes.SetUserString(key, keys[key]);
                if (doc.Objects.Add(geometry, attributes) != Guid.Empty)
                    count++;
                if (attributes.GetUserString("sida.kind") == "origin")
                {
                    doc.Strings.SetString("sida.origin", attributes.GetUserString("sida.origin") ?? "");
                    var project = attributes.GetUserString("sida.project");
                    if (!string.IsNullOrEmpty(project))
                        Meanings.SetProject(doc, project!);
                }
            }
            doc.Views.Redraw();
            return count;
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
