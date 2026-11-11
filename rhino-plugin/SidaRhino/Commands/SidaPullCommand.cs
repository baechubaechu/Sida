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
                var count = Importer.Import(doc, client.Export3dm(project));
                RhinoApp.WriteLine($"Sida: 제도판을 가져왔습니다 ({count}개 개체, 레이어 {Importer.ParentLayer}).");
                if (Importer.KeptLast > 0)
                    RhinoApp.WriteLine($"Sida: 전에 가져온 뒤 고친 개체 {Importer.KeptLast}개는 그대로 두었습니다 (이제 내 개체입니다).");
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
