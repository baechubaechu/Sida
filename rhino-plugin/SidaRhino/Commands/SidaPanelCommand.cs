using Rhino;
using Rhino.Commands;
using Rhino.UI;

namespace SidaRhino.Commands
{
    /// <summary>SidaPanel: open (or close) the Sida panel.</summary>
    public class SidaPanelCommand : Command
    {
        public override string EnglishName => "SidaPanel";

        protected override Result RunCommand(RhinoDoc doc, RunMode mode)
        {
            var id = SidaPanel.PanelId;
            if (Panels.IsPanelVisible(id))
                Panels.ClosePanel(id);
            else
                Panels.OpenPanel(id);
            return Result.Success;
        }
    }
}
