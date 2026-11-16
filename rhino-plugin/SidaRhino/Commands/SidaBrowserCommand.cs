using Rhino;
using Rhino.Commands;

namespace SidaRhino.Commands
{
    /// <summary>SidaBrowser: the panel's page in the default browser (a second screen, or a Rhino whose web view does not work).</summary>
    public class SidaBrowserCommand : Command
    {
        public override string EnglishName => "SidaBrowser";

        protected override Result RunCommand(RhinoDoc doc, RunMode mode)
        {
            LiveLink.Ensure();
            LiveLink.OpenInBrowser();
            return Result.Success;
        }
    }
}
