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
            var project = Meanings.Project(doc);
            if (project == null)
            {
                RhinoApp.WriteLine("Sida: 먼저 SidaPanel에서 프로젝트를 고르세요.");
                return Result.Cancel;
            }
            try
            {
                var client = new SidaClient();
                if (client.Hello() == null)
                {
                    RhinoApp.WriteLine("Sida: Sida 앱이 꺼져 있습니다. run.bat으로 켠 뒤 다시 하세요.");
                    return Result.Failure;
                }
                var snapshot = SnapshotBuilder.Build(doc, withMeshes: true);
                var views = SnapshotBuilder.Capture(doc, snapshot);
                var answer = client.Push(project, snapshot, views);
                RhinoApp.WriteLine($"Sida: 보냈습니다 (스냅샷 {answer.SnapshotId}).");
                foreach (var line in answer.Lines)
                    RhinoApp.WriteLine("  " + line);
                return Result.Success;
            }
            catch (SidaException exc)
            {
                RhinoApp.WriteLine("Sida: " + exc.Message);
                return Result.Failure;
            }
        }
    }
}
