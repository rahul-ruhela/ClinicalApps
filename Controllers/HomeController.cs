using System.Diagnostics;
using System.Text.Json.Serialization;
using ClinicalApps.Models;
using Microsoft.AspNetCore.Mvc;

namespace ClinicalApps.Controllers
{
    public class HomeController : Controller
    {
        private readonly ILogger<HomeController> _logger;
        private readonly PythonApiService _python;

        public HomeController(ILogger<HomeController> logger, PythonApiService python)
        {
            _logger = logger;
            _python = python;
        }

        public IActionResult Index() => View();
        public IActionResult Privacy() => View();
        public IActionResult Demo() => View();
        public IActionResult UserTracking() => View();

        // ── Discharge API ──────────────────────────────────────────────────

        [HttpGet("/api/discharge/patients")]
        public async Task<IActionResult> GetPatients()
        {
            try
            {
                var result = await _python.GetPatientsAsync();
                return Json(result);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "GetPatients failed");
                return StatusCode(500, new { error = ex.Message });
            }
        }

        [HttpPost("/api/discharge/generate")]
        public async Task<IActionResult> GenerateDischarge([FromBody] GenerateRequest req)
        {
            try
            {
                var result = await _python.GenerateDischargeAsync(req.PatientName, req.Language ?? "en");
                return Json(result);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "GenerateDischarge failed");
                return StatusCode(500, new { error = ex.Message });
            }
        }

        [HttpPost("/api/discharge/generate-from-upload")]
        public async Task<IActionResult> GenerateFromUpload([FromBody] GenerateFromUploadRequest req)
        {
            try
            {
                var result = await _python.GenerateFromUploadAsync(
                    req.MedicalText,
                    req.PatientName ?? "Patient",
                    req.Language ?? "en");
                return Json(result);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "GenerateFromUpload failed");
                return StatusCode(500, new { error = ex.Message });
            }
        }

        [HttpPost("/api/discharge/simplify")]
        public async Task<IActionResult> SimplifyDischarge([FromBody] SimplifyRequest req)
        {
            try
            {
                var result = await _python.SimplifyDischargeAsync(req.Summary, req.TargetGrade);
                return Json(result);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "SimplifyDischarge failed");
                return StatusCode(500, new { error = ex.Message });
            }
        }

        // ── User Tracking ──────────────────────────────────────────────────

        [HttpPost("/api/track-user")]
        public async Task<IActionResult> TrackUser([FromBody] TrackUserRequest req)
        {
            try
            {
                var result = await _python.TrackUserAsync(req.Name, req.Email, req.Page);
                return Json(result);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "TrackUser failed");
                return StatusCode(500, new { error = ex.Message });
            }
        }

        [HttpGet("/api/tracked-users")]
        public async Task<IActionResult> GetTrackedUsers()
        {
            try
            {
                var result = await _python.GetTrackedUsersAsync();
                return Json(result);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "GetTrackedUsers failed");
                return StatusCode(500, new { error = ex.Message });
            }
        }

        [HttpDelete("/api/tracked-users/{index}")]
        public async Task<IActionResult> DeleteTrackedUser(int index)
        {
            try
            {
                var result = await _python.DeleteTrackedUserAsync(index);
                return Json(result);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "DeleteTrackedUser failed");
                return StatusCode(500, new { error = ex.Message });
            }
        }

        [HttpDelete("/api/tracked-users/clear")]
        public async Task<IActionResult> ClearTrackedUsers()
        {
            try
            {
                var result = await _python.ClearTrackedUsersAsync();
                return Json(result);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "ClearTrackedUsers failed");
                return StatusCode(500, new { error = ex.Message });
            }
        }

        // ── Audit Logs ─────────────────────────────────────────────────────

        [HttpGet("/api/audit/logs")]
        public async Task<IActionResult> GetAuditLogs(string? date, string? event_type, int limit = 100)
        {
            try
            {
                var result = await _python.GetAuditLogsAsync(date, event_type, limit);
                return Json(result);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "GetAuditLogs failed");
                return StatusCode(500, new { error = ex.Message });
            }
        }

        // ──────────────────────────────────────────────────────────────────

        [ResponseCache(Duration = 0, Location = ResponseCacheLocation.None, NoStore = true)]
        public IActionResult Error()
        {
            return View(new ErrorViewModel { RequestId = Activity.Current?.Id ?? HttpContext.TraceIdentifier });
        }
    }

    // Request models — [JsonPropertyName] maps JS snake_case to C# PascalCase
    public record GenerateRequest(
        [property: JsonPropertyName("patient_name")] string PatientName,
        string? Language);

    public record SimplifyRequest(
        string Summary,
        [property: JsonPropertyName("target_grade")] int TargetGrade = 7);

    public record GenerateFromUploadRequest(
        [property: JsonPropertyName("medical_text")] string MedicalText,
        [property: JsonPropertyName("patient_name")] string? PatientName,
        string? Language);

    public record TrackUserRequest(string Name, string Email, string Page);
}
