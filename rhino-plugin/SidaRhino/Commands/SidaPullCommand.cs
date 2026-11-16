using Rhino;
using Rhino.Commands;

namespace SidaRhino.Commands
{
    /// <summary>SidaPull: the drafting table of this document's Sida project into the document.</summary>
    public class SidaPullCommand : Command
    {
        public override string EnglishName => "SidaPull";

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
                if (client.Hello() == null)
                {
                    LiveLink.Say("Sida 앱이 꺼져 있습니다. run.bat으로 켠 뒤 다시 하세요.", ok: false);
                    return Result.Failure;
                }
                RhinoApp.WriteLine("Sida: 제도판을 가져오는 중입니다. 이 프로젝트를 처음 가져올 때는 주변 건물을 만드느라 30초쯤 걸릴 수 있습니다.");
                RhinoApp.Wait();  // so the line shows before the wait
                var count = Importer.Import(doc, client.Export3dm(project));
                var kept = Importer.KeptLast > 0 ? $" 전에 가져온 뒤 고친 개체 {Importer.KeptLast}개는 그대로 두었습니다." : "";
                LiveLink.Say($"제도판을 가져왔습니다 (개체 {count}개, 레이어 {Importer.ParentLayer}).{kept}");
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
