using System.Diagnostics;
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
            var result = await _python.GetPatientsAsync();
            return Json(result);
        }

        [HttpPost("/api/discharge/generate")]
        public async Task<IActionResult> GenerateDischarge([FromBody] GenerateRequest req)
        {
            var result = await _python.GenerateDischargeAsync(req.PatientName, req.Language ?? "en");
            return Json(result);
        }

        [HttpPost("/api/discharge/simplify")]
        public async Task<IActionResult> SimplifyDischarge([FromBody] SimplifyRequest req)
        {
            var result = await _python.SimplifyDischargeAsync(req.Summary, req.TargetGrade);
            return Json(result);
        }

        // ── User Tracking ──────────────────────────────────────────────────

        [HttpPost("/api/track-user")]
        public async Task<IActionResult> TrackUser([FromBody] TrackUserRequest req)
        {
            var result = await _python.TrackUserAsync(req.Name, req.Email, req.Page);
            return Json(result);
        }

        [HttpGet("/api/tracked-users")]
        public async Task<IActionResult> GetTrackedUsers()
        {
            var result = await _python.GetTrackedUsersAsync();
            return Json(result);
        }

        [HttpDelete("/api/tracked-users/{index}")]
        public async Task<IActionResult> DeleteTrackedUser(int index)
        {
            var result = await _python.DeleteTrackedUserAsync(index);
            return Json(result);
        }

        [HttpDelete("/api/tracked-users/clear")]
        public async Task<IActionResult> ClearTrackedUsers()
        {
            var result = await _python.ClearTrackedUsersAsync();
            return Json(result);
        }

        // ── Audit Logs ─────────────────────────────────────────────────────

        [HttpGet("/api/audit/logs")]
        public async Task<IActionResult> GetAuditLogs(string? date, string? event_type, int limit = 100)
        {
            var result = await _python.GetAuditLogsAsync(date, event_type, limit);
            return Json(result);
        }

        // ──────────────────────────────────────────────────────────────────

        [ResponseCache(Duration = 0, Location = ResponseCacheLocation.None, NoStore = true)]
        public IActionResult Error()
        {
            return View(new ErrorViewModel { RequestId = Activity.Current?.Id ?? HttpContext.TraceIdentifier });
        }
    }

    // Request models
    public record GenerateRequest(string PatientName, string? Language);
    public record SimplifyRequest(string Summary, int TargetGrade = 7);
    public record TrackUserRequest(string Name, string Email, string Page);
}
