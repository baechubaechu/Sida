using Rhino;
using Rhino.Commands;

namespace SidaRhino.Commands
{
    /// <summary>SidaPush: what Rhino measured in this document, with view captures, to Sida.</summary>
    public class SidaPushCommand : Command
    {
        public override string EnglishName => "SidaPush";

        protected override Result RunCommand(RhinoDoc doc, RunMode mode)
        {
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
                var answer = client.Push(project, snapshot, views);
                LiveLink.Say("Sida로 보냈습니다. Sida 제도판의 \"라이노 작업\" 종이에서 볼 수 있습니다.");
                foreach (var line in answer.Lines)
                    RhinoApp.WriteLine("  " + line);
                return Result.Success;
            }
            catch (SidaException exc)
            {
                LiveLink.Say(exc.Message, ok: false);
                return Result.Failure;
            }
        }
    }
}
