using System.Diagnostics;
using System.Net;
using System.Windows.Forms;

internal static class Program
{
    private const string Url = "http://127.0.0.1:9876/";
    private const string AppHost = "127.0.0.1";
    private const string AppPort = "9876";
    private const string RequiredVersion = "1.5.1";

    [STAThread]
    private static async Task Main()
    {
        string appDir = AppContext.BaseDirectory;
        string appPath = Path.Combine(appDir, "app.py");
        string dataDir = Path.Combine(appDir, "data");
        Directory.CreateDirectory(dataDir);
        string stdoutLog = Path.Combine(dataDir, "server.out.log");
        string stderrLog = Path.Combine(dataDir, "server.err.log");
        string launcherLog = Path.Combine(dataDir, "launcher.log");

        if (!File.Exists(appPath))
        {
            MessageBox.Show(
                $"app.py was not found next to the launcher:\n{appPath}",
                "RuTracker Release Checker",
                MessageBoxButtons.OK,
                MessageBoxIcon.Error
            );
            return;
        }

        ServerState state = await GetServerState();
        if (state.IsChecker)
        {
            StartTrayIfBackgroundEnabled(appDir, state.BackgroundEnabled);
            OpenBrowser();
            return;
        }

        if (state.IsUp)
        {
            MessageBox.Show(
                "Port 9876 is already used by another local service, so RuTracker Release Checker cannot start.\n\nClose that process or free http://127.0.0.1:9876/, then try again.",
                "RuTracker Release Checker",
                MessageBoxButtons.OK,
                MessageBoxIcon.Warning
            );
            return;
        }

        if (!state.IsUp)
        {
            PythonCommand? python = FindPython();
            if (python is null)
            {
                MessageBox.Show(
                    "Python was not found. Install Python 3.11+ or run .\\run.ps1 from the project folder.",
                    "RuTracker Release Checker",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Error
                );
                return;
            }

            try
            {
                File.AppendAllText(
                    launcherLog,
                    $"{DateTime.Now:O} starting server with {python.FileName} {python.ArgumentPrefix}\"{appPath}\"{Environment.NewLine}"
                );
                Process.Start(new ProcessStartInfo
                {
                    FileName = "cmd.exe",
                    Arguments = $"/d /c \"{Quote(python.FileName)} {python.ArgumentPrefix}{Quote(appPath)} >> {Quote(stdoutLog)} 2>> {Quote(stderrLog)}\"",
                    WorkingDirectory = appDir,
                    UseShellExecute = false,
                    CreateNoWindow = true,
                    WindowStyle = ProcessWindowStyle.Hidden,
                    Environment =
                    {
                        ["APP_HOST"] = AppHost,
                        ["APP_PORT"] = AppPort
                    }
                });
            }
            catch (Exception ex)
            {
                File.AppendAllText(
                    launcherLog,
                    $"{DateTime.Now:O} start failed: {ex}{Environment.NewLine}"
                );
                MessageBox.Show(
                    $"Could not start the local server:\n{ex.Message}",
                    "RuTracker Release Checker",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Error
                );
                return;
            }
        }

        if (!await WaitForServer())
        {
            MessageBox.Show(
                "The local server did not start on http://127.0.0.1:9876/.\n\nDiagnostics were written to:\n" +
                launcherLog + "\n" +
                stdoutLog + "\n" +
                stderrLog,
                "RuTracker Release Checker",
                MessageBoxButtons.OK,
                MessageBoxIcon.Warning
            );
            return;
        }

        state = await GetServerState();
        StartTrayIfBackgroundEnabled(appDir, state.BackgroundEnabled);
        OpenBrowser();
    }

    private static void OpenBrowser()
    {
        Process.Start(new ProcessStartInfo
        {
            FileName = Url,
            UseShellExecute = true
        });
    }

    private static void StartTrayIfBackgroundEnabled(string appDir, bool backgroundEnabled)
    {
        if (!backgroundEnabled)
        {
            return;
        }

        string trayScript = Path.Combine(appDir, "scripts", "start-tray.ps1");
        if (!File.Exists(trayScript))
        {
            return;
        }

        try
        {
            ProcessStartInfo startInfo = new()
            {
                FileName = "powershell.exe",
                WorkingDirectory = appDir,
                UseShellExecute = false,
                CreateNoWindow = true,
                WindowStyle = ProcessWindowStyle.Hidden
            };
            startInfo.ArgumentList.Add("-STA");
            startInfo.ArgumentList.Add("-NoProfile");
            startInfo.ArgumentList.Add("-ExecutionPolicy");
            startInfo.ArgumentList.Add("Bypass");
            startInfo.ArgumentList.Add("-WindowStyle");
            startInfo.ArgumentList.Add("Hidden");
            startInfo.ArgumentList.Add("-File");
            startInfo.ArgumentList.Add(trayScript);
            Process.Start(startInfo);
        }
        catch
        {
            // The UI still works if the tray cannot be started.
        }
    }

    private static bool ReadJsonBool(string body, string name)
    {
        string marker = "\"" + name + "\":";
        int index = body.IndexOf(marker, StringComparison.OrdinalIgnoreCase);
        if (index < 0)
        {
            return false;
        }
        int valueStart = index + marker.Length;
        while (valueStart < body.Length && char.IsWhiteSpace(body[valueStart]))
        {
            valueStart++;
        }
        return body.Substring(valueStart).StartsWith("true", StringComparison.OrdinalIgnoreCase);
    }

    private static PythonCommand? FindPython()
    {
        string? explicitPython = Environment.GetEnvironmentVariable("RUTRACKER_CHECKER_PYTHON");
        if (!string.IsNullOrWhiteSpace(explicitPython) && File.Exists(explicitPython))
        {
            return new PythonCommand(explicitPython, "");
        }

        string bundled = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
            ".cache",
            "codex-runtimes",
            "codex-primary-runtime",
            "dependencies",
            "python",
            "python.exe"
        );
        if (File.Exists(bundled))
        {
            return new PythonCommand(bundled, "");
        }

        if (CanRun("python.exe", "--version"))
        {
            return new PythonCommand("python.exe", "");
        }

        if (CanRun("py.exe", "-3 --version"))
        {
            return new PythonCommand("py.exe", "-3 ");
        }

        return null;
    }

    private static bool CanRun(string fileName, string arguments)
    {
        try
        {
            using Process process = Process.Start(new ProcessStartInfo
            {
                FileName = fileName,
                Arguments = arguments,
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true
            })!;
            process.WaitForExit(3000);
            return process.ExitCode == 0;
        }
        catch
        {
            return false;
        }
    }

    private static string Quote(string value)
    {
        return "\"" + value.Replace("\"", "\\\"") + "\"";
    }

    private static async Task<bool> WaitForServer()
    {
        DateTime deadline = DateTime.UtcNow.AddSeconds(12);
        while (DateTime.UtcNow < deadline)
        {
            ServerState state = await GetServerState();
            if (state.IsChecker)
            {
                return true;
            }
            await Task.Delay(500);
        }
        return false;
    }

    private static async Task<ServerState> GetServerState()
    {
        try
        {
            using HttpClient client = new()
            {
                Timeout = TimeSpan.FromSeconds(1)
            };
            using HttpResponseMessage response = await client.GetAsync(Url + "api/health");
            if (response.StatusCode != HttpStatusCode.OK)
            {
                return new ServerState(true, false, "", false);
            }

            string body = await response.Content.ReadAsStringAsync();
            string marker = "\"version\":";
            int index = body.IndexOf(marker, StringComparison.OrdinalIgnoreCase);
            if (index < 0)
            {
                return new ServerState(true, false, "", false);
            }
            int quoteStart = body.IndexOf('"', index + marker.Length);
            int quoteEnd = quoteStart >= 0 ? body.IndexOf('"', quoteStart + 1) : -1;
            string version = quoteStart >= 0 && quoteEnd > quoteStart
                ? body.Substring(quoteStart + 1, quoteEnd - quoteStart - 1)
                : "";
            return new ServerState(true, true, version, ReadJsonBool(body, "background_enabled"));
        }
        catch
        {
            return new ServerState(false, false, "", false);
        }
    }

    private sealed record PythonCommand(string FileName, string ArgumentPrefix);
    private sealed record ServerState(bool IsUp, bool IsChecker, string Version, bool BackgroundEnabled);
}
