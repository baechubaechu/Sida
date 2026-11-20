using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using Rhino;
using Rhino.Commands;
using Rhino.DocObjects;
using Rhino.Geometry;
using Rhino.Input;
using Rhino.Input.Custom;

namespace SidaRhino.Commands
{
    /// <summary>
    /// SidaLandscape: 자동 조경 in a closed curve the designer picks (Enter: the whole lot). The model
    /// is pushed first, so the buildings the 조경 keeps clear of are the document's own; Sida lays
    /// the 조경 out by rule (docs/landscape.md) and answers a drawing instruction, drawn in place on
    /// sublayers of "Sida 조경" (Drawer). The style and the seed are kept in the document, so
    /// running it again draws the same plan, and Shuffle draws the next one.
    /// </summary>
    public class SidaLandscapeCommand : Command
    {
        /// <summary>The style and shuffle the panel asked for, for the next run only (no options asked then).</summary>
        public static (string Style, bool Shuffle)? Asked { get; set; }

        private static readonly string[] Styles = { "formal", "natural", "plaza" };
        private static readonly string[] Options = { "Formal", "Natural", "Plaza" };
        private static readonly string[] Words = { "정형", "자연형", "광장형" };
        private const string StyleKey = "sida.landscape.style";
        private const string SeedKey = "sida.landscape.seed";
        private const int MaxPoints = 200;  // Sida takes a region of up to this many corners

        public override string EnglishName => "SidaLandscape";

        protected override Result RunCommand(RhinoDoc doc, RunMode mode)
        {
            var asked = Asked;
            Asked = null;
            LiveLink.Ensure();
            var project = Meanings.Project(doc);
            if (project == null)
            {
                LiveLink.Say("먼저 SidaPanel에서 이 문서의 Sida 프로젝트를 고르세요.", ok: false);
                return Result.Cancel;
            }
            var styleIndex = Math.Max(0, Array.IndexOf(Styles, asked?.Style ?? doc.Strings.GetValue(StyleKey) ?? "formal"));
            var seed = int.TryParse(doc.Strings.GetValue(SeedKey), NumberStyles.Integer, CultureInfo.InvariantCulture, out var kept)
                && kept >= 1 && kept <= 9999 ? kept : 1;
            var shuffle = new OptionToggle(asked?.Shuffle ?? false, "No", "Yes");

            var go = new GetObject();
            go.SetCommandPrompt("조경할 영역의 닫힌 커브를 고르세요 (Enter: 대지 전체)");
            go.GeometryFilter = ObjectType.Curve;
            go.GeometryAttributeFilter = GeometryAttributeFilter.ClosedCurve;
            go.AcceptNothing(true);
            go.EnablePreSelect(true, true);
            Curve? curve = null;
            while (true)
            {
                go.ClearCommandOptions();
                if (asked == null)
                {
                    go.AddOptionList("Style", Options, styleIndex);
                    go.AddOptionToggle("Shuffle", ref shuffle);
                }
                var got = go.Get();
                if (got == GetResult.Option)
                {
                    if (go.Option().EnglishName == "Style")
                        styleIndex = go.Option().CurrentListOptionIndex;
                    continue;
                }
                if (got == GetResult.Nothing)
                    break;
                if (got != GetResult.Object)
                    return Result.Cancel;
                curve = go.Object(0).Curve();
                break;
            }

            List<double[]>? region = null;
            if (curve != null)
            {
                region = Corners(curve, doc);
                if (region == null)
                {
                    LiveLink.Say("평평하게 닫힌 커브를 고르세요. 영역은 평면에 그린 닫힌 커브여야 합니다.", ok: false);
                    return Result.Cancel;
                }
            }
            if (shuffle.CurrentValue)
                seed = seed % 9999 + 1;
            var style = Styles[styleIndex];

            try
            {
                var client = new SidaClient();
                var meanings = client.Hello();
                if (meanings == null)
                {
                    LiveLink.Say("Sida 앱이 꺼져 있습니다. run.bat으로 켠 뒤 다시 하세요.", ok: false);
                    return Result.Failure;
                }
                var snapshot = SnapshotBuilder.Build(doc, Meanings.Built(meanings), withMeshes: true);
                var views = SnapshotBuilder.Capture(doc, snapshot);
                var pushed = client.Push(project, snapshot, views);
                using var answer = client.Landscape(project, pushed.SnapshotId ?? "", region, style, seed);
                var root = answer.RootElement;
                var made = Drawer.Draw(doc, root.GetProperty("drawing"));
                doc.Strings.SetString(StyleKey, style);
                doc.Strings.SetString(SeedKey, seed.ToString(CultureInfo.InvariantCulture));
                doc.Views.Redraw();
                var lines = root.GetProperty("lines").EnumerateArray().Select(l => l.GetString() ?? "").ToList();
                foreach (var line in lines)
                    RhinoApp.WriteLine("  " + line);
                var note = root.TryGetProperty("roads_note", out var n) ? n.GetString() ?? "" : "";
                var said = $"조경 {Words[styleIndex]} 안을 {(region == null ? "대지 전체" : "고른 영역")}에 그렸습니다 (레이어 Sida 조경). "
                    + string.Join(", ", lines) + (note.Length > 0 ? $". {note}" : "");
                LiveLink.Say(said, ok: made > 0);
                return made > 0 ? Result.Success : Result.Nothing;
            }
            catch (SidaException exc)
            {
                LiveLink.Say(exc.Message, ok: false);
                return Result.Failure;
            }
        }

        /// <summary>
        /// The curve's corners in metres ([x, y], at most MaxPoints, the closing point left out): a
        /// polyline's own, else points along it about a metre apart. Null for a curve that is not
        /// planar and closed.
        /// </summary>
        private static List<double[]>? Corners(Curve curve, RhinoDoc doc)
        {
            if (!curve.IsClosed || !curve.IsPlanar(doc.ModelAbsoluteTolerance))
                return null;
            var toMetres = RhinoMath.UnitScale(doc.ModelUnitSystem, UnitSystem.Meters);
            Point3d[] points;
            if (curve.TryGetPolyline(out var polyline))
            {
                points = polyline.ToArray();
            }
            else
            {
                var count = (int)Math.Clamp(curve.GetLength() * toMetres, 12, MaxPoints);
                curve.DivideByCount(count, true, out points);
            }
            if (points == null || points.Length < 3)
                return null;
            var list = points.ToList();
            if (list.Count > 1 && list[0].DistanceTo(list[list.Count - 1]) <= doc.ModelAbsoluteTolerance)
                list.RemoveAt(list.Count - 1);
            if (list.Count > MaxPoints)  // a fine polyline: every so many of its corners
            {
                var step = (int)Math.Ceiling(list.Count / (double)MaxPoints);
                list = list.Where((_, i) => i % step == 0).ToList();
            }
            return list.Count < 3 ? null : list.Select(p => new[] { Math.Round(p.X * toMetres, 3), Math.Round(p.Y * toMetres, 3) }).ToList();
        }
    }
}
