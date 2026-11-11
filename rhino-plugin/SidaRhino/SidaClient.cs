using System;
using System.Collections.Generic;
using System.Net.Http;
using System.Text;
using System.Text.Encodings.Web;
using System.Text.Json;

namespace SidaRhino
{
    /// <summary>One Sida project as the app lists it.</summary>
    public sealed record SidaProject(string Name, string DisplayName);

    /// <summary>A layer meaning Sida knows (from /api/rhino/hello): its code and Korean word.</summary>
    public sealed record Meaning(string Code, string Word, bool Built);

    /// <summary>What Sida answered to a push or a live figures request.</summary>
    public sealed record FigureLines(IReadOnlyList<string> Lines, string? SnapshotId);

    /// <summary>
    /// The HTTP side: Sida runs on this PC at 127.0.0.1:8765 (docs/rhino-api.md). Calls are
    /// synchronous and short; Rhino commands run on the UI thread and the server is local.
    /// </summary>
    public sealed class SidaClient
    {
        public const string DefaultBaseUrl = "http://127.0.0.1:8765";
        public const int Schema = 1;

        private static readonly HttpClient Http = new HttpClient { Timeout = TimeSpan.FromSeconds(60) };
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
                using var doc = GetJson("/api/rhino/hello");
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

        public IReadOnlyList<SidaProject> Projects()
        {
            using var doc = GetJson("/api/projects");
            var projects = new List<SidaProject>();
            foreach (var item in doc.RootElement.GetProperty("projects").EnumerateArray())
            {
                var name = item.GetProperty("name").GetString() ?? "";
                var shown = item.TryGetProperty("display_name", out var d) && d.ValueKind == JsonValueKind.String ? d.GetString() : null;
                projects.Add(new SidaProject(name, string.IsNullOrWhiteSpace(shown) ? name : shown!));
            }
            return projects;
        }

        /// <summary>The drafting table as a 3dm file in metres (the board export).</summary>
        public byte[] Export3dm(string project)
        {
            var response = Http.GetAsync($"{BaseUrl}/api/projects/{Uri.EscapeDataString(project)}/board/export?format=3dm")
                .GetAwaiter().GetResult();
            EnsureOk(response);
            return response.Content.ReadAsByteArrayAsync().GetAwaiter().GetResult();
        }

        /// <summary>Send a snapshot with its view images; Sida saves it and answers its figures.</summary>
        public FigureLines Push(string project, Dictionary<string, object?> snapshot, IReadOnlyDictionary<string, byte[]> views)
        {
            using var form = new MultipartFormDataContent();
            form.Add(new StringContent(JsonSerializer.Serialize(snapshot, JsonOptions), Encoding.UTF8, "application/json"), "snapshot");
            foreach (var (file, bytes) in views)
            {
                var part = new ByteArrayContent(bytes);
                part.Headers.ContentType = new System.Net.Http.Headers.MediaTypeHeaderValue("image/png");
                form.Add(part, "views", file);
            }
            var response = Http.PostAsync($"{BaseUrl}/api/projects/{Uri.EscapeDataString(project)}/rhino/snapshots", form)
                .GetAwaiter().GetResult();
            EnsureOk(response);
            using var doc = JsonDocument.Parse(response.Content.ReadAsStringAsync().GetAwaiter().GetResult());
            return new FigureLines(Lines(doc.RootElement.GetProperty("figures")), doc.RootElement.GetProperty("snapshot").GetProperty("id").GetString());
        }

        /// <summary>Figures for a snapshot Sida does not keep (the panel while the designer models).</summary>
        public FigureLines Figures(string project, Dictionary<string, object?> snapshot)
        {
            var body = new StringContent(JsonSerializer.Serialize(snapshot, JsonOptions), Encoding.UTF8, "application/json");
            var response = Http.PostAsync($"{BaseUrl}/api/projects/{Uri.EscapeDataString(project)}/rhino/figures", body)
                .GetAwaiter().GetResult();
            EnsureOk(response);
            using var doc = JsonDocument.Parse(response.Content.ReadAsStringAsync().GetAwaiter().GetResult());
            return new FigureLines(Lines(doc.RootElement.GetProperty("figures")), null);
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
            var response = Http.GetAsync(BaseUrl + path).GetAwaiter().GetResult();
            EnsureOk(response);
            return JsonDocument.Parse(response.Content.ReadAsStringAsync().GetAwaiter().GetResult());
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
