using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Drawing.Imaging;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using Rhino;
using Rhino.Commands;

namespace SidaRhino
{
    /// <summary>
    /// The running link to Sida (docs/rhino-api.md, "실시간"): the panel in Rhino is a Sida page
    /// that never talks to Rhino, so this class tells Sida how the active document stands and
    /// asks Sida what the panel wants done.
    ///
    /// One background loop asks every half second (all HTTP stays off Rhino's UI thread: a closed
    /// port on Windows takes seconds to refuse). Whatever touches the document runs on the UI
    /// thread, between commands: the loop wakes it with InvokeOnUiThread when there is a command
    /// to do or a change to report. The document is measured again only for objects that
    /// changed (SnapshotBuilder's cache), and at most about once a second.
    /// </summary>
    public static class LiveLink
    {
        private const int AskEveryMs = 500;
        private const int WhenDownMs = 3000;
        private const int ReportEveryMs = 700;
        private const int MaxSelected = 200;  // selected objects named in a report (Sida takes no more)
        private const int ViewLongEdge = 1024;  // pixels on the long side of the view sent with a question

        private static readonly SidaClient Client = new SidaClient();
        private static readonly ConcurrentQueue<JsonElement> Waiting = new ConcurrentQueue<JsonElement>();
        private static readonly Dictionary<Guid, SnapshotBuilder.Measured> Cache = new Dictionary<Guid, SnapshotBuilder.Measured>();
        private static readonly object Gate = new object();
        private static CancellationTokenSource? _stop;
        private static HashSet<string>? _built;   // the meanings Sida counts as building; null until Sida answered hello
        private static long _done;                // the last command done (sent as `after`)
        private static long _queued;              // the last command put in Waiting
        private static int _misses;               // answers missed in a row
        private static volatile bool _dirty = true;
        private static volatile bool _sending;
        private static volatile bool _pumping;
        private static volatile bool _pushOnIdle;  // a save asked for a push (autosync)
        private static Notice? _notice;           // what the last pull or push said, until Sida has heard it
        private static DateTime _lastReport = DateTime.MinValue;
        private static string? _refused;          // why Sida refused the last report (said once)
        private static volatile string _busy = "";  // what is in the middle of being done for the panel ("pull"), "" for nothing
        private static volatile Pulled? _pulled;   // a drafting table downloaded in the background, waiting to be put in the document

        /// <summary>The drafting table of `Project` as a 3dm file, or why it could not be had.</summary>
        private sealed record Pulled(string Project, byte[]? File, string? Error);

        private sealed record Notice(string Text, bool Ok);

        /// <summary>The id Sida knows this Rhino by: one live document per running Rhino (its active document).</summary>
        public static string DocId { get; } = $"rhino-{Environment.ProcessId}";

        /// <summary>Sida answers (one missed answer does not count: Sida may be busy for a moment).</summary>
        public static bool Up { get; private set; }

        /// <summary>Why Sida cannot be used although something answers at its address (an older Sida); null otherwise.</summary>
        public static string? Problem { get; private set; }

        /// <summary>The panel page for this Rhino.</summary>
        public static string PanelUrl => $"{Client.BaseUrl}/app/rhino.html?doc={Uri.EscapeDataString(DocId)}";

        /// <summary>Start the link (once); the panel and the commands call this.</summary>
        public static void Ensure()
        {
            lock (Gate)
            {
                if (_stop != null)
                    return;
                _stop = new CancellationTokenSource();
                RhinoDoc.AddRhinoObject += (s, e) => _dirty = true;
                RhinoDoc.DeleteRhinoObject += (s, e) => _dirty = true;
                RhinoDoc.UndeleteRhinoObject += (s, e) => _dirty = true;
                RhinoDoc.ReplaceRhinoObject += (s, e) => _dirty = true;
                RhinoDoc.ModifyObjectAttributes += (s, e) => _dirty = true;
                RhinoDoc.LayerTableEvent += (s, e) => _dirty = true;
                RhinoDoc.DocumentPropertiesChanged += (s, e) => _dirty = true;
                // What is selected goes with the report, so a question asked in the panel is about "this one".
                RhinoDoc.SelectObjects += (s, e) => _dirty = true;
                RhinoDoc.DeselectObjects += (s, e) => _dirty = true;
                RhinoDoc.DeselectAllObjects += (s, e) => _dirty = true;
                RhinoDoc.EndOpenDocument += (s, e) => Reset();
                RhinoDoc.NewDocument += (s, e) => Reset();
                RhinoDoc.ActiveDocumentChanged += (s, e) => Reset();
                RhinoDoc.EndSaveDocument += (s, e) =>
                {
                    _dirty = true;  // the file name may be new
                    var doc = RhinoDoc.FromRuntimeSerialNumber(e.DocumentSerialNumber);
                    if (doc != null && !e.ExportSelected && Meanings.Autosync(doc) && Meanings.Project(doc) != null)
                        _pushOnIdle = true;
                };
                var token = _stop.Token;
                Task.Run(() => Loop(token), token);
            }
        }

        /// <summary>The panel's page in the default browser.</summary>
        public static void OpenInBrowser()
        {
            try
            {
                System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo(PanelUrl) { UseShellExecute = true });
            }
            catch (Exception exc)
            {
                RhinoApp.WriteLine($"Sida: 브라우저를 열지 못했습니다 ({exc.Message}). 주소: {PanelUrl}");
            }
        }

        /// <summary>Something the designer should see in the panel (the result of a pull or a push).</summary>
        public static void Say(string text, bool ok = true)
        {
            RhinoApp.WriteLine("Sida: " + text);
            _notice = new Notice(text, ok);
            _dirty = true;
        }

        /// <summary>Have the document reported again soon (a layer's meaning or the project changed).</summary>
        public static void Touch() => _dirty = true;

        private static void Reset()
        {
            lock (Cache)
                Cache.Clear();
            _dirty = true;
        }

        private static async Task Loop(CancellationToken stop)
        {
            while (!stop.IsCancellationRequested)
            {
                var wait = AskEveryMs;
                try
                {
                    if (_built == null)
                    {
                        var meanings = Client.Hello();
                        if (meanings != null)
                            _built = Meanings.Built(meanings);
                    }
                    if (_built == null)
                    {
                        Up = false;  // nothing listens at Sida's address
                        Problem = null;
                        wait = WhenDownMs;
                    }
                    else
                    {
                        using var answer = Client.Pending(DocId, Interlocked.Read(ref _done));
                        Up = true;
                        Problem = null;
                        _misses = 0;
                        var root = answer.RootElement;
                        if (!root.GetProperty("known").GetBoolean() && _refused == null)
                            _dirty = true;  // Sida does not have this document (it restarted): say it again
                        foreach (var command in root.GetProperty("commands").EnumerateArray())
                        {
                            var id = command.GetProperty("id").GetInt64();
                            if (id <= _queued)
                                continue;  // already waiting here; Sida repeats a command until it hears it is done
                            _queued = id;
                            Waiting.Enqueue(command.Clone());
                        }
                        if ((!Waiting.IsEmpty || _dirty || _pushOnIdle || _pulled != null) && !_pumping)
                        {
                            _pumping = true;
                            RhinoApp.InvokeOnUiThread(new Action(Pump));
                        }
                    }
                }
                catch (Exception exc) when (exc is SidaException || exc is System.Net.Http.HttpRequestException || exc is TaskCanceledException || exc is JsonException || exc is KeyNotFoundException)
                {
                    if (_built == null || ++_misses >= 2)
                    {
                        Up = false;
                        Problem = _built == null && exc is SidaException ? exc.Message : null;  // hello said why (an older Sida)
                        _built = null;  // ask hello again when Sida is back (it may be another version)
                        wait = WhenDownMs;
                    }
                }
                try
                {
                    await Task.Delay(wait, stop).ConfigureAwait(false);
                }
                catch (TaskCanceledException)
                {
                    return;
                }
            }
        }

        /// <summary>On Rhino's UI thread: do what the panel asked, then say how the document stands.</summary>
        private static void Pump()
        {
            try
            {
                if (Command.InCommand())
                    return;  // the designer is in the middle of something; the next round tries again
                var doc = RhinoDoc.ActiveDoc;
                if (doc == null)
                    return;
                while (Waiting.TryDequeue(out var command))
                {
                    try
                    {
                        Do(doc, command);
                    }
                    catch (Exception exc)
                    {
                        Say("패널이 부탁한 일을 하지 못했습니다: " + exc.Message, ok: false);
                    }
                    Interlocked.Exchange(ref _done, command.GetProperty("id").GetInt64());
                }
                var pulled = _pulled;
                if (pulled != null)
                {
                    _pulled = null;
                    _busy = "";
                    PutIn(doc, pulled);
                }
                if (_pushOnIdle)
                {
                    _pushOnIdle = false;
                    RhinoApp.RunScript("_SidaPush", false);
                }
                var built = _built;
                if (_dirty && built != null && !_sending && (DateTime.UtcNow - _lastReport).TotalMilliseconds >= ReportEveryMs)
                {
                    _dirty = false;
                    _lastReport = DateTime.UtcNow;
                    var notice = _notice;
                    _notice = null;
                    var report = Report(doc, built, notice);
                    _sending = true;
                    Task.Run(() =>
                    {
                        try
                        {
                            Client.Report(report);
                            _refused = null;
                        }
                        catch (SidaException exc)
                        {
                            // Sida read it and said no (a document beyond its limits). Saying the same
                            // again changes nothing: wait for the document to change, and say why once.
                            _notice ??= notice;
                            if (_refused != exc.Message)
                            {
                                _refused = exc.Message;
                                RhinoApp.WriteLine("Sida: 이 문서를 패널에 보여 줄 수 없습니다. " + exc.Message);
                            }
                        }
                        catch (Exception)
                        {
                            _notice ??= notice;
                            _dirty = true;  // not heard: say it again on a later round
                        }
                        finally
                        {
                            _sending = false;
                        }
                    });
                }
            }
            catch (Exception exc)
            {
                RhinoApp.WriteLine("Sida: 패널과 연결하는 중 문제가 생겼습니다: " + exc.Message);
            }
            finally
            {
                _pumping = false;
            }
        }

        private static Dictionary<string, object?> Report(RhinoDoc doc, HashSet<string> built, Notice? notice)
        {
            Dictionary<string, object?> snapshot;
            lock (Cache)
                snapshot = SnapshotBuilder.Build(doc, built, withMeshes: false, cache: Cache);
            var report = new Dictionary<string, object?>
            {
                ["doc"] = DocId,
                ["file"] = string.IsNullOrEmpty(doc.Name) ? "" : doc.Name,
                ["units"] = doc.ModelUnitSystem.ToString(),
                ["project"] = Meanings.Project(doc) ?? "",
                ["autosync"] = Meanings.Autosync(doc),
                ["busy"] = _busy,
                ["snapshot"] = snapshot,
            };
            // The selection by id (the first MaxSelected; the count says how many there are in all).
            var selected = new List<string>();
            var count = 0;
            foreach (var picked in doc.Objects.GetSelectedObjects(false, false))
            {
                count++;
                if (selected.Count < MaxSelected)
                    selected.Add(picked.Id.ToString());
            }
            report["selected"] = selected;
            report["selected_count"] = count;
            if (notice != null)
                report["notice"] = new Dictionary<string, object?> { ["text"] = notice.Text, ["ok"] = notice.Ok };
            return report;
        }

        /// <summary>
        /// The panel's "Sida에서 가져오기": the download runs in the background (the first export of
        /// a project builds its surroundings on the server, half a minute and more), so Rhino stays
        /// usable; the file is put in the document on the UI thread when it has arrived (PutIn).
        /// The SidaPull command typed in Rhino does the same in one go.
        /// </summary>
        private static void BeginPull(RhinoDoc doc)
        {
            var project = Meanings.Project(doc);
            if (project == null)
            {
                Say("먼저 이 문서의 Sida 프로젝트를 고르세요.", ok: false);
                return;
            }
            if (_busy.Length > 0)
                return;  // one at a time
            _busy = "pull";
            RhinoApp.WriteLine("Sida: 제도판을 가져오는 중입니다. 이 프로젝트를 처음 가져올 때는 30초쯤 걸릴 수 있고, 그동안 라이노는 그대로 쓸 수 있습니다.");
            Task.Run(() =>
            {
                try
                {
                    _pulled = new Pulled(project, Client.Export3dm(project), null);
                }
                catch (Exception exc)
                {
                    _pulled = new Pulled(project, null, exc is SidaException ? exc.Message : "제도판을 받지 못했습니다: " + exc.Message);
                }
            });
        }

        private static void PutIn(RhinoDoc doc, Pulled pulled)
        {
            if (pulled.File == null)
            {
                Say(pulled.Error ?? "제도판을 받지 못했습니다.", ok: false);
                return;
            }
            if (Meanings.Project(doc) != pulled.Project)
            {
                Say("기다리는 동안 문서나 프로젝트가 바뀌어, 받은 제도판을 넣지 않았습니다.", ok: false);
                return;
            }
            var record = doc.BeginUndoRecord("SidaPull");  // outside a command: one undo step of its own
            try
            {
                Say(Importer.Said(Importer.Import(doc, pulled.File)));
            }
            catch (SidaException exc)
            {
                Say(exc.Message, ok: false);
            }
            finally
            {
                doc.EndUndoRecord(record);
            }
        }

        private static void Do(RhinoDoc doc, JsonElement command)
        {
            string? text(string key) => command.TryGetProperty(key, out var value) && value.ValueKind == JsonValueKind.String ? value.GetString() : null;
            switch (text("type"))
            {
                case "pull":
                    BeginPull(doc);
                    break;
                case "draw":
                    Commands.SidaDrawCommand.Asked = command.TryGetProperty("kinds", out var kinds) && kinds.ValueKind == JsonValueKind.Array
                        ? kinds.EnumerateArray().Select(k => k.GetString() ?? "").ToList() : null;
                    RhinoApp.RunScript("_SidaDraw", false);
                    break;
                case "push":
                    RhinoApp.RunScript("_SidaPush", false);
                    break;
                case "landscape":
                    Commands.SidaLandscapeCommand.Asked = (text("style") ?? "formal",
                        command.TryGetProperty("shuffle", out var shuffle) && shuffle.ValueKind == JsonValueKind.True);
                    RhinoApp.RunScript("_SidaLandscape", false);
                    break;
                case "set_project":
                    var project = text("project");
                    if (!string.IsNullOrEmpty(project))
                        Meanings.SetProject(doc, project!);
                    break;
                case "set_layer":
                    var index = doc.Layers.FindByFullPath(text("path") ?? "", -1);
                    if (index < 0)
                        throw new SidaException($"레이어 '{text("path")}'가 이 문서에 없습니다.");
                    double? height = null;  // the panel speaks metres; the layer keeps document units
                    if (command.TryGetProperty("floor_height", out var metres) && metres.ValueKind == JsonValueKind.Number)
                        height = metres.GetDouble() / RhinoMath.UnitScale(doc.ModelUnitSystem, UnitSystem.Meters);
                    Meanings.Set(doc, index, text("meaning") ?? "", height);
                    break;
                case "set_autosync":
                    Meanings.SetAutosync(doc, command.TryGetProperty("on", out var on) && on.ValueKind == JsonValueKind.True);
                    break;
                case "report":
                    break;  // the report below is the answer
                case "view":
                    SendView(doc, command.GetProperty("id").GetInt64());
                    return;  // nothing in the document changed
            }
            _dirty = true;
        }

        /// <summary>
        /// Sida asks for the active viewport as it is now: a question to Sida takes it along
        /// when the designer switched that on. Captured here on the UI thread as the viewport
        /// shows it (its display mode, what is hidden), in the viewport's proportions with
        /// ViewLongEdge pixels on the long side, and sent in the background. When nothing can be sent Sida stops waiting after
        /// a few seconds and tells the designer the question went without a picture.
        /// </summary>
        private static void SendView(RhinoDoc doc, long id)
        {
            var view = doc.Views.ActiveView;
            if (view == null)
                return;
            var size = view.ActiveViewport.Size;
            // Drawn again at this size, not a copy of the screen: a small viewport (four on a small window)
            // would give a picture too small to read (305 pixels wide on a PC, 2026-11-17).
            var scale = (double)ViewLongEdge / Math.Max(1, Math.Max(size.Width, size.Height));
            var target = new System.Drawing.Size(Math.Max(1, (int)Math.Round(size.Width * scale)), Math.Max(1, (int)Math.Round(size.Height * scale)));
            byte[] png;
            using (var bitmap = view.CaptureToBitmap(target))
            {
                if (bitmap == null)
                    return;
                using var stream = new MemoryStream();
                bitmap.Save(stream, ImageFormat.Png);
                png = stream.ToArray();
            }
            var title = view.ActiveViewport.Name ?? "";
            if (title.Length > 80)
                title = title.Substring(0, 80);
            Task.Run(() =>
            {
                try
                {
                    Client.View(DocId, id, title, png);
                }
                catch (Exception)
                {
                    // not heard: Sida says that no picture came
                }
            });
        }
    }
}
