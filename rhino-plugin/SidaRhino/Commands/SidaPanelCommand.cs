using Rhino;
using Rhino.Commands;
using Rhino.UI;

namespace SidaRhino.Commands
{
    /// <summary>
    /// SidaPanel: show the Sida panel. The first time it opens as a tab beside Layers (a panel
    /// opened on its own comes up as a small floating window); after that Rhino remembers where
    /// the designer put it.
    /// </summary>
    public class SidaPanelCommand : Command
    {
        public override string EnglishName => "SidaPanel";

        protected override Result RunCommand(RhinoDoc doc, RunMode mode)
        {
            var id = SidaPanel.PanelId;
            if (Panels.IsPanelVisible(id) || !Panels.OpenPanelAsSibling(id, PanelIds.Layers))
                Panels.OpenPanel(id, true);
            return Result.Success;
        }
    }
}
