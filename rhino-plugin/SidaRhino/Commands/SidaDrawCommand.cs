using System.Collections.Generic;
using System.Linq;
using Rhino;
using Rhino.Commands;

namespace SidaRhino.Commands
{
    /// <summary>
    /// SidaDraw: the document's diagrams as geometry on the "Sida 다이어그램" layer. The model is
    /// pushed first (so Sida draws what the document holds now, and its "라이노 작업" paper shows
    /// the same diagrams), then each drawing instruction Sida answers is drawn as it is.
    /// </summary>
    public class SidaDrawCommand : Command
    {
        /// <summary>The kinds the panel asked for, for the next run only; null draws every kind that can be drawn.</summary>
        public static IReadOnlyCollection<string>? Asked { get; set; }

        public override string EnglishName => "SidaDraw";

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
                var drawn = new List<string>();
                var left = new List<string>();
                foreach (var (kind, title, ready, reason) in client.Diagrams(project, pushed.SnapshotId ?? ""))
                {
                    if (asked != null && !asked.Contains(kind))
                        continue;
                    if (!ready)
                    {
                        left.Add($"{title}: {reason}");
                        continue;
                    }
                    using var drawing = client.Drawing(project, pushed.SnapshotId ?? "", kind);
                    if (Drawer.Draw(doc, drawing.RootElement.GetProperty("drawing")) > 0)
                        drawn.Add(title);
                }
                doc.Views.Redraw();
                var said = drawn.Count > 0
                    ? $"다이어그램 {drawn.Count}개를 그렸습니다 ({string.Join(", ", drawn)}). 모델 동쪽, 레이어 {Drawer.ParentLayer}에 있습니다."
                    : "그릴 수 있는 다이어그램이 없습니다.";
                if (left.Count > 0)
                    said += " 그리지 못한 것: " + string.Join(" ", left);
                LiveLink.Say(said, ok: drawn.Count > 0);
                return drawn.Count > 0 ? Result.Success : Result.Nothing;
            }
            catch (SidaException exc)
            {
                LiveLink.Say(exc.Message, ok: false);
                return Result.Failure;
            }
        }
    }
}
