using System;
using System.Collections.Generic;
using System.Globalization;
using Rhino;
using Rhino.DocObjects;

namespace SidaRhino
{
    /// <summary>
    /// What the designer told Sida about this document, kept in the document itself (user
    /// strings on the layers and the document), so it survives saving and reopening:
    /// the Sida project the document belongs to, and each layer's meaning and floor height.
    /// Nothing is inferred; a layer without a meaning stays out of the figures.
    /// </summary>
    public static class Meanings
    {
        public const string ProjectKey = "sida.project";
        public const string MeaningKey = "sida.meaning";
        public const string FloorHeightKey = "sida.floor_height";

        public static string? Project(RhinoDoc doc)
        {
            var name = doc.Strings.GetValue(ProjectKey);
            return string.IsNullOrWhiteSpace(name) ? null : name;
        }

        public static void SetProject(RhinoDoc doc, string name)
        {
            doc.Strings.SetString(ProjectKey, name);
        }

        public static string MeaningOf(Layer layer)
        {
            return layer.GetUserString(MeaningKey) ?? "";
        }

        /// <summary>The layer's floor height in document units, or null when the designer set none.</summary>
        public static double? FloorHeightOf(Layer layer)
        {
            var raw = layer.GetUserString(FloorHeightKey);
            return double.TryParse(raw, NumberStyles.Float, CultureInfo.InvariantCulture, out var value) && value > 0 ? value : null;
        }

        public static void Set(RhinoDoc doc, int layerIndex, string meaning, double? floorHeight)
        {
            var layer = doc.Layers.FindIndex(layerIndex);
            if (layer == null)
                return;
            layer.SetUserString(MeaningKey, meaning ?? "");
            layer.SetUserString(FloorHeightKey, floorHeight.HasValue ? floorHeight.Value.ToString("0.###", CultureInfo.InvariantCulture) : "");
            doc.Layers.Modify(layer, layerIndex, true);
        }

        /// <summary>The meaning codes Sida counts as building, as it said in /api/rhino/hello.</summary>
        public static HashSet<string> Built(IEnumerable<Meaning> meanings)
        {
            var codes = new HashSet<string>();
            foreach (var meaning in meanings)
            {
                if (meaning.Built)
                    codes.Add(meaning.Code);
            }
            return codes;
        }

        /// <summary>Every layer with its meaning and floor height, in table order.</summary>
        public static IReadOnlyList<(Layer Layer, string Meaning, double? FloorHeight)> All(RhinoDoc doc)
        {
            var out_ = new List<(Layer, string, double?)>();
            foreach (var layer in doc.Layers)
            {
                if (layer.IsDeleted)
                    continue;
                out_.Add((layer, MeaningOf(layer), FloorHeightOf(layer)));
            }
            return out_;
        }
    }
}
