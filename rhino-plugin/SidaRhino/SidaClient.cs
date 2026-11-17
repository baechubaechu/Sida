using System;
using System.Collections.Generic;
using System.Net.Http;
using System.Text;
using System.Text.Encodings.Web;
using System.Text.Json;

namespace SidaRhino
{
    /// <summary>A layer meaning Sida knows (from /api/rhino/hello): its code and Korean word.</summary>
    public sealed record Meaning(string Code, string Word, bool Built);

    /// <summary>What Sida answered to a push: its figure lines and the snapshot it saved.</summary>
    public sealed record FigureLines(IReadOnlyList<string> Lines, string? SnapshotId);

    /// <summary>
    /// The HTTP side: Sida runs on this PC at 127.0.0.1:8765 (docs/rhino-api.md). Calls are
    /// synchronous: the commands (pull, push) make theirs on Rhino's UI thread, the live link
    /// makes its own on a background thread.
    /// </summary>
    public sealed class SidaClient
    {
        public const string DefaultBaseUrl = "http://127.0.0.1:8765";
        public const int Schema = 1;

        // Long: the first export of a project builds its surroundings on the server (half a minute and more).
        private static readonly HttpClient Http = new HttpClient { Timeout = TimeSpan.FromSeconds(300) };
        // Short: the live link asks twice a second from a background thread and must notice a stopped Sida soon.
        private static readonly HttpClient Quick = new HttpClient { Timeout = TimeSpan.FromSeconds(8) };
        private static readonly JsonSerializerOptions JsonOptions = new JsonSerializerOptions
        {
            Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
        };

        public SidaClient(string? baseUrl = null)
        {
            BaseUrl = (baseUrl ?? Environment.GetEnvironmentVariable("SIDA_URL") ?? DefaultBaseUrl).TrimEnd('/');
        }

        public string BaseUrl { get; }

        /// <summary>Sida is up and reads this plugin's snapshot schema. Null when it is not reachable.</summary>
        public IReadOnlyList<Meaning>? Hello()
        {
            try
            {
                using var response = Quick.GetAsync(BaseUrl + "/api/rhino/hello").GetAwaiter().GetResult();
                if (response.StatusCode == System.Net.HttpStatusCode.NotFound)
                    throw new SidaException("켜져 있는 Sida가 라이노 연결보다 오래된 버전입니다. Sida를 업데이트한 뒤 다시 하세요.");
                EnsureOk(response);
                using var doc = JsonDocument.Parse(response.Content.ReadAsStringAsync().GetAwaiter().GetResult());
                var root = doc.RootElement;
                if (!root.TryGetProperty("ok", out var ok) || !ok.GetBoolean())
                    return null;
                if (root.GetProperty("schema").GetInt32() != Schema)
                    throw new SidaException($"이 플러그인은 스냅샷 형식 {Schema}을 보내는데 Sida는 {root.GetProperty("schema").GetInt32()}을 읽습니다. 둘 중 하나를 업데이트하세요.");
                var meanings = new List<Meaning>();
                foreach (var item in root.GetProperty("meanings").EnumerateArray())
                    meanings.Add(new Meaning(item.GetProperty("code").GetString() ?? "", item.GetProperty("word").GetString() ?? "",
                        item.GetProperty("built").GetBoolean()));
                return meanings;
            }
            catch (HttpRequestException)
            {
                return null;
            }
            catch (System.Threading.Tasks.TaskCanceledException)
            {
                return null;  // timed out: Sida is not answering
            }
        }

        /// <summary>The drafting table as a 3dm file in metres (the board export).</summary>
        public byte[] Export3dm(string project)
        {
            var response = Sent(() => Http.GetAsync($"{BaseUrl}/api/projects/{Uri.EscapeDataString(project)}/board/export?format=3dm")
                .GetAwaiter().GetResult());
            EnsureOk(response);
            return response.Content.ReadAsByteArrayAsync().GetAwaiter().GetResult();
        }

        /// <summary>Send a snapshot with its view images; Sida saves it and answers its figures.</summary>
        public FigureLines Push(string project, Dictionary<string, object?> snapshot, IReadOnlyDictionary<string, byte[]> views)
        {
            using var form = new MultipartFormDataContent();
            // A file part, not a form field: with its meshes the snapshot is megabytes and Sida's server stops a field at 1 MB.
            var json = new ByteArrayContent(JsonSerializer.SerializeToUtf8Bytes(snapshot, JsonOptions));
            json.Headers.ContentType = new System.Net.Http.Headers.MediaTypeHeaderValue("application/json");
            form.Add(json, "snapshot", "snapshot.json");
            foreach (var (file, bytes) in views)
            {
                var part = new ByteArrayContent(bytes);
                part.Headers.ContentType = new System.Net.Http.Headers.MediaTypeHeaderValue("image/png");
                form.Add(part, "views", file);
            }
            var response = Sent(() => Http.PostAsync($"{BaseUrl}/api/projects/{Uri.EscapeDataString(project)}/rhino/snapshots", form)
                .GetAwaiter().GetResult());
            EnsureOk(response);
            using var doc = JsonDocument.Parse(response.Content.ReadAsStringAsync().GetAwaiter().GetResult());
            return new FigureLines(Lines(doc.RootElement.GetProperty("figures")), doc.RootElement.GetProperty("snapshot").GetProperty("id").GetString());
        }

        /// <summary>The kinds of diagram and whether the snapshot can be drawn as each (kind, Korean title, ready, why not).</summary>
        public IReadOnlyList<(string Kind, string Title, bool Ready, string Reason)> Diagrams(string project, string snapshotId)
        {
            using var doc = GetJson($"/api/projects/{Uri.EscapeDataString(project)}/rhino/snapshots/{Uri.EscapeDataString(snapshotId)}/diagrams");
            var list = new List<(string, string, bool, string)>();
            foreach (var item in doc.RootElement.GetProperty("diagrams").EnumerateArray())
                list.Add((item.GetProperty("kind").GetString() ?? "", item.GetProperty("title").GetString() ?? "",
                    item.GetProperty("ready").GetBoolean(), item.GetProperty("reason").GetString() ?? ""));
            return list;
        }

        /// <summary>One diagram's drawing instruction ({drawing}), in metres in the snapshot's frame.</summary>
        public JsonDocument Drawing(string project, string snapshotId, string kind)
        {
            return GetJson($"/api/projects/{Uri.EscapeDataString(project)}/rhino/snapshots/{Uri.EscapeDataString(snapshotId)}/diagrams/{Uri.EscapeDataString(kind)}");
        }

        /// <summary>What the panel wants done next ({known, commands}); asking is also this Rhino's heartbeat.</summary>
        public JsonDocument Pending(string doc, long after)
        {
            var response = Quick.GetAsync($"{BaseUrl}/api/rhino/commands?doc={Uri.EscapeDataString(doc)}&after={after}").GetAwaiter().GetResult();
            EnsureOk(response);
            return JsonDocument.Parse(response.Content.ReadAsStringAsync().GetAwaiter().GetResult());
        }

        /// <summary>Tell Sida how the document stands (the live panel reads it).</summary>
        public void Report(Dictionary<string, object?> report)
        {
            var body = new StringContent(JsonSerializer.Serialize(report, JsonOptions), Encoding.UTF8, "application/json");
            EnsureOk(Quick.PostAsync($"{BaseUrl}/api/rhino/live", body).GetAwaiter().GetResult());
        }

        /// <summary>The active viewport as a PNG, for the question to Sida that asked for it (the command `view`).</summary>
        public void View(string doc, long command, string title, byte[] png)
        {
            using var form = new MultipartFormDataContent();
            var part = new ByteArrayContent(png);
            part.Headers.ContentType = new System.Net.Http.Headers.MediaTypeHeaderValue("image/png");
            form.Add(part, "view", "view.png");
            var url = $"{BaseUrl}/api/rhino/live/view?doc={Uri.EscapeDataString(doc)}&command={command}&title={Uri.EscapeDataString(title)}";
            EnsureOk(Quick.PostAsync(url, form).GetAwaiter().GetResult());
        }

        private static IReadOnlyList<string> Lines(JsonElement figures)
        {
            var lines = new List<string>();
            foreach (var line in figures.GetProperty("lines").EnumerateArray())
                lines.Add(line.GetString() ?? "");
            return lines;
        }

        private JsonDocument GetJson(string path)
        {
            var response = Sent(() => Http.GetAsync(BaseUrl + path).GetAwaiter().GetResult());
            EnsureOk(response);
            return JsonDocument.Parse(response.Content.ReadAsStringAsync().GetAwaiter().GetResult());
        }

        private static HttpResponseMessage Sent(Func<HttpResponseMessage> send)
        {
            try
            {
                return send();
            }
            catch (HttpRequestException)
            {
                throw new SidaException("Sida 앱과 연결이 끊겼습니다. Sida가 켜져 있는지 확인한 뒤 다시 하세요.");
            }
            catch (System.Threading.Tasks.TaskCanceledException)
            {
                throw new SidaException("Sida가 너무 오래 대답하지 않습니다. Sida 창을 확인한 뒤 다시 하세요.");
            }
        }

        private static void EnsureOk(HttpResponseMessage response)
        {
            if (response.IsSuccessStatusCode)
                return;
            var text = response.Content.ReadAsStringAsync().GetAwaiter().GetResult();
            string detail = text;
            try
            {
                using var doc = JsonDocument.Parse(text);
                if (doc.RootElement.TryGetProperty("detail", out var d) && d.ValueKind == JsonValueKind.String)
                    detail = d.GetString() ?? text;
            }
            catch (JsonException)
            {
                // not JSON: the text itself is the message
            }
            throw new SidaException($"Sida가 거부했습니다 ({(int)response.StatusCode}): {detail}");
        }
    }

    /// <summary>A message for the designer (Korean), not a crash.</summary>
    public sealed class SidaException : Exception
    {
        public SidaException(string message) : base(message)
        {
        }
    }
}
