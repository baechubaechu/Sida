using System.Runtime.InteropServices;
using Rhino.PlugIns;

// What Rhino's plug-in manager shows for Sida.
[assembly: PlugInDescription(DescriptionType.Organization, "Sida team")]
[assembly: PlugInDescription(DescriptionType.WebSite, "https://sida-kr.duckdns.org")]

// The id of the plug-in in Rhino. It must never change: Rhino keeps the plug-in's settings and
// its registration under it.
[assembly: Guid("5B1F6C0E-3A47-4D9B-8E21-7C4A9D2F6B10")]
