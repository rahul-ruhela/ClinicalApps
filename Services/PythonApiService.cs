using System.Net.Http.Json;
using System.Text.Json;

/// <summary>
/// Wraps all Python backend API calls. Flask runs on localhost:5002.
/// </summary>
public class PythonApiService
{
    private readonly HttpClient _http;

    public PythonApiService(IHttpClientFactory factory)
    {
        _http = factory.CreateClient("PythonApi");
    }

    // GET /api/discharge/patients
    public async Task<JsonElement> GetPatientsAsync()
    {
        var response = await _http.GetAsync("/api/discharge/patients");
        return await response.Content.ReadFromJsonAsync<JsonElement>();
    }

    // POST /api/discharge/generate
    public async Task<JsonElement> GenerateDischargeAsync(string patientName, string language = "en")
    {
        var response = await _http.PostAsJsonAsync("/api/discharge/generate", new
        {
            patient_name = patientName,
            language
        });
        return await response.Content.ReadFromJsonAsync<JsonElement>();
    }

    // POST /api/discharge/simplify
    public async Task<JsonElement> SimplifyDischargeAsync(string summary, int targetGrade = 7)
    {
        var response = await _http.PostAsJsonAsync("/api/discharge/simplify", new
        {
            summary,
            target_grade = targetGrade
        });
        return await response.Content.ReadFromJsonAsync<JsonElement>();
    }

    // POST /api/track-user
    public async Task<JsonElement> TrackUserAsync(string name, string email, string page)
    {
        var response = await _http.PostAsJsonAsync("/api/track-user", new
        {
            name,
            email,
            page,
            timestamp = DateTime.UtcNow.ToString("o")
        });
        return await response.Content.ReadFromJsonAsync<JsonElement>();
    }

    // GET /api/tracked-users
    public async Task<JsonElement> GetTrackedUsersAsync()
    {
        var response = await _http.GetAsync("/api/tracked-users");
        return await response.Content.ReadFromJsonAsync<JsonElement>();
    }

    // DELETE /api/tracked-users/{index}
    public async Task<JsonElement> DeleteTrackedUserAsync(int index)
    {
        var response = await _http.DeleteAsync($"/api/tracked-users/{index}");
        return await response.Content.ReadFromJsonAsync<JsonElement>();
    }

    // DELETE /api/tracked-users/clear
    public async Task<JsonElement> ClearTrackedUsersAsync()
    {
        var response = await _http.DeleteAsync("/api/tracked-users/clear");
        return await response.Content.ReadFromJsonAsync<JsonElement>();
    }

    // GET /api/audit/logs
    public async Task<JsonElement> GetAuditLogsAsync(string? date = null, string? eventType = null, int limit = 100)
    {
        var query = $"/api/audit/logs?limit={limit}";
        if (date != null) query += $"&date={date}";
        if (eventType != null) query += $"&event_type={eventType}";

        var response = await _http.GetAsync(query);
        return await response.Content.ReadFromJsonAsync<JsonElement>();
    }
}
