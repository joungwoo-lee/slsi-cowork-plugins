using System.Diagnostics;

namespace DocUnlockCli;

/// <summary>
/// Tracks Office process PIDs spawned by this tool and force-kills them on timeout.
/// Prevents zombie processes from DRM popups or hangs.
/// </summary>
public sealed class ProcessWatchdog : IDisposable
{
    private readonly string _processName;
    private readonly HashSet<int> _preExistingPids;
    private readonly int _timeoutMs;
    private int? _trackedPid;
    private bool _disposed;

    public ProcessWatchdog(string processName, int timeoutMs = 20_000)
    {
        _processName = processName;
        _timeoutMs = timeoutMs;
        _preExistingPids = GetCurrentPids(processName);
    }

    public void DetectNewProcess()
    {
        if (_trackedPid is int trackedPid)
        {
            try
            {
                using var proc = Process.GetProcessById(trackedPid);
                if (!proc.HasExited) return;
            }
            catch (ArgumentException)
            {
            }
        }

        var currentPids = GetCurrentPids(_processName);
        var newPids = currentPids.Except(_preExistingPids).ToList();
        if (newPids.Count > 0)
        {
            _trackedPid = newPids.Max();
            Log($"Tracked new {_processName} PID: {_trackedPid}");
        }
    }

    public void KillIfRunning()
    {
        if (_trackedPid is null) return;

        try
        {
            var proc = Process.GetProcessById(_trackedPid.Value);
            if (!proc.HasExited)
            {
                Log($"Force-killing {_processName} PID {_trackedPid}");
                proc.Kill(entireProcessTree: true);
                proc.WaitForExit(5000);
            }
        }
        catch (ArgumentException)
        {
            // Process already exited
        }
        catch (Exception ex)
        {
            Log($"Warning: Could not kill PID {_trackedPid}: {ex.Message}");
        }
    }

    public int TimeoutMs => _timeoutMs;

    public int? TrackedPid => _trackedPid;

    private static HashSet<int> GetCurrentPids(string processName)
    {
        return Process.GetProcessesByName(processName)
            .Select(p => p.Id)
            .ToHashSet();
    }

    private static void Log(string message)
    {
        Console.Error.WriteLine($"[Watchdog] {message}");
    }

    public void Dispose()
    {
        if (_disposed) return;
        _disposed = true;
        KillIfRunning();
    }
}
