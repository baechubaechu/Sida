using System;
using Rhino;
using Rhino.PlugIns;
using Rhino.UI;

namespace SidaRhino
{
    /// <summary>
    /// Sida for Rhino. Commands: SidaPull (the drafting table into this document), SidaPush (what
    /// Rhino measured, to Sida), SidaPanel (the panel). Nothing here decides a figure: Sida does.
    /// </summary>
    public class SidaRhinoPlugIn : PlugIn
    {
        public SidaRhinoPlugIn()
        {
            Instance = this;
        }

        public static SidaRhinoPlugIn? Instance { get; private set; }

        public override PlugInLoadTime LoadTime => PlugInLoadTime.AtStartup;

        protected override LoadReturnCode OnLoad(ref string errorMessage)
        {
            Panels.RegisterPanel(this, typeof(SidaPanel), "Sida", System.Drawing.SystemIcons.Application);
            RhinoApp.WriteLine("Sida: SidaPanel 명령으로 패널을 엽니다. Sida 앱(127.0.0.1:8765)이 켜져 있어야 합니다.");
            return LoadReturnCode.Success;
        }
    }
}
