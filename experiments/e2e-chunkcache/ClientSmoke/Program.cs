// A7 client smoke. Usage: ClientSmoke <base-url> <request.json> [api-key]
// request.json: { "model": "...", "system": "...", "prompt": "<joined tool-result text>", "query": "...",
//                 "chunks": [ { "id": "...", "text": "<exact substring of prompt>" } ], "max_tokens": 16 }
// Prints the parsed chunk_cache report (as the client lifted it) plus the manifest outcome as one JSON object.
using System.ClientModel;
using System.ClientModel.Primitives;
using System.Text.Json;
using System.Text.Json.Nodes;
using DotLLM.ChunkCache.Client;
using Microsoft.Extensions.AI;
using OpenAI;

string baseUrl = args[0];
JsonObject req = JsonNode.Parse(File.ReadAllText(args[1]))!.AsObject();
string? apiKey = args.Length > 2 ? args[2] : null;
string model = (string)req["model"]!;
string prompt = (string)req["prompt"]!;

var baseUri = new Uri(baseUrl.TrimEnd('/') + "/");
var capsSource = new ChunkCapabilityCache(new ChunkCacheHttpClient(new HttpClient(), baseUri, apiKey));
var handler = new ChunkCacheBodyHandler(capsSource) { InnerHandler = new HttpClientHandler() };
using var http = new HttpClient(handler);
var options = new OpenAIClientOptions
{
    Endpoint = new Uri(baseUri, "v1/"),
    Transport = new HttpClientPipelineTransport(http),
    RetryPolicy = new ClientRetryPolicy(maxRetries: 0),
};
IChatClient inner = new OpenAI.Chat.ChatClient(model, new ApiKeyCredential(apiKey ?? "none"), options).AsIChatClient();

var registry = new ChunkSpanRegistry();
var spans = new List<ChunkSpan>();
foreach (JsonNode? c in req["chunks"]!.AsArray())
{
    string text = (string)c!["text"]!;
    int start = prompt.IndexOf(text, StringComparison.Ordinal);
    if (start < 0) throw new InvalidOperationException("chunk text not in prompt: " + (string)c["id"]!);
    spans.Add(new ChunkSpan((string)c["id"]!, ChunkHash.Of(text), start, start + text.Length, "symbol-512"));
}
registry.Register(prompt, spans);

ChunkCacheCallEventArgs? completed = null;
var client = new ChunkAnnotatingChatClient(inner, registry, new ShadowPolicy(), new ChunkAnnotatingOptions { Capabilities = capsSource });
client.CallCompleted += (_, e) => completed = e;

var messages = new List<ChatMessage>
{
    new(ChatRole.System, (string)req["system"]!),
    new(ChatRole.User, prompt),
    new(ChatRole.User, (string)req["query"]!),
};
ChatResponse response = await client.GetResponseAsync(messages, new ChatOptions { MaxOutputTokens = (int?)req["max_tokens"] ?? 16, Temperature = 0 });
ChunkCacheReport.TryGet(response, out JsonObject? report);
var result = new JsonObject
{
    ["text"] = response.Text,
    ["report"] = report?.DeepClone(),
    ["outcome"] = completed?.Outcome is { } o
        ? new JsonObject { ["annotated"] = o.Annotated, ["skip_reason"] = o.SkipReason, ["registered"] = o.RegisteredSpans, ["sent"] = o.SentSpans }
        : null,
};
Console.WriteLine(result.ToJsonString());
return report is null ? 2 : 0;

sealed class ShadowPolicy : IRecomputePolicy
{
    public ChunkRequestOptions Decide(ChunkRequestContext context) => new(Policy: "shadow", Report: "per_chunk");
}
