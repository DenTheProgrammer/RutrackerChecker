using System.Diagnostics;
using System.Net;
using System.Runtime.InteropServices;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;
using System.Windows.Forms;

internal static class Program
{
    private const string Url = "http://127.0.0.1:9876/";
    private const string AppHost = "127.0.0.1";
    private const string AppPort = "9876";
    private const string RequiredVersion = "1.5.1";
    private const string ShortcutName = "RuTracker Checker.lnk";
    private const string ShortcutPromptFileName = "desktop-shortcut-prompted.flag";

    [STAThread]
    private static async Task Main(string[] args)
    {
        Application.SetHighDpiMode(HighDpiMode.PerMonitorV2);

        bool serverOnly = args.Any(arg => arg.Equals("--server-only", StringComparison.OrdinalIgnoreCase));
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

        PromptForDesktopShortcutIfNeeded(appDir, dataDir, launcherLog);

        ServerState state = await GetServerState();
        if (state.IsChecker)
        {
            StartTrayIfBackgroundEnabled(appDir, state.BackgroundEnabled);
            if (serverOnly)
            {
                return;
            }
            OpenAppWindow(dataDir, launcherLog);
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
        if (serverOnly)
        {
            return;
        }
        OpenAppWindow(dataDir, launcherLog);
    }

    private static void OpenAppWindow(string dataDir, string launcherLog)
    {
        Exception? windowError = null;
        Thread uiThread = new(() =>
        {
            try
            {
                Application.EnableVisualStyles();
                Application.SetCompatibleTextRenderingDefault(false);
                using BrowserForm form = new(Url, dataDir, launcherLog);
                Application.Run(form);
            }
            catch (Exception ex)
            {
                windowError = ex;
            }
        });
        uiThread.SetApartmentState(ApartmentState.STA);
        uiThread.Start();
        uiThread.Join();

        if (windowError is null)
        {
            return;
        }

        AppendLauncherLog(launcherLog, "app window failed", windowError);
        MessageBox.Show(
            "Could not open the app window. The WebView2 Runtime may be missing or unavailable.\n\nOpening RuTracker Checker in your browser instead.",
            "RuTracker Checker",
            MessageBoxButtons.OK,
            MessageBoxIcon.Warning
        );
        OpenExternalUrl(Url);
    }

    private static void OpenExternalUrl(string url)
    {
        Process.Start(new ProcessStartInfo
        {
            FileName = url,
            UseShellExecute = true
        });
    }

    private static void AppendLauncherLog(string launcherLog, string message, Exception ex)
    {
        try
        {
            File.AppendAllText(
                launcherLog,
                $"{DateTime.Now:O} {message}: {ex}{Environment.NewLine}"
            );
        }
        catch
        {
        }
    }

    private sealed class BrowserForm : Form
    {
        private readonly string url;
        private readonly string dataDir;
        private readonly string launcherLog;
        private readonly WebView2 webView;
        private bool didInitialize;

        public BrowserForm(string url, string dataDir, string launcherLog)
        {
            this.url = url;
            this.dataDir = dataDir;
            this.launcherLog = launcherLog;

            Text = "RuTracker Checker";
            StartPosition = FormStartPosition.CenterScreen;
            Size = new Size(1180, 800);
            MinimumSize = new Size(920, 640);
            WindowState = FormWindowState.Maximized;

            Icon? appIcon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
            if (appIcon is not null)
            {
                Icon = appIcon;
            }

            webView = new WebView2
            {
                Dock = DockStyle.Fill,
                AllowExternalDrop = false
            };
            Controls.Add(webView);
        }

        protected override async void OnShown(EventArgs e)
        {
            base.OnShown(e);
            if (didInitialize)
            {
                return;
            }

            didInitialize = true;
            try
            {
                await InitializeWebView();
            }
            catch (Exception ex)
            {
                AppendLauncherLog(launcherLog, "webview initialization failed", ex);
                MessageBox.Show(
                    "Could not open the app window. The WebView2 Runtime may be missing or unavailable.\n\nOpening RuTracker Checker in your browser instead.",
                    "RuTracker Checker",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Warning
                );
                OpenExternalUrl(url);
                BeginInvoke(Close);
            }
        }

        private async Task InitializeWebView()
        {
            string userDataFolder = Path.Combine(dataDir, "webview2");
            Directory.CreateDirectory(userDataFolder);
            CoreWebView2Environment environment = await CoreWebView2Environment.CreateAsync(null, userDataFolder);
            await webView.EnsureCoreWebView2Async(environment);

            CoreWebView2 core = webView.CoreWebView2;
            core.NewWindowRequested += (_, args) =>
            {
                args.Handled = true;
                if (IsAppUrl(args.Uri))
                {
                    core.Navigate(args.Uri);
                    return;
                }
                OpenExternalUrl(args.Uri);
            };
            core.NavigationStarting += (_, args) =>
            {
                if (IsAppUrl(args.Uri) || args.Uri.StartsWith("about:", StringComparison.OrdinalIgnoreCase))
                {
                    return;
                }

                args.Cancel = true;
                OpenExternalUrl(args.Uri);
            };
            core.Navigate(url);
        }

        private static bool IsAppUrl(string value)
        {
            if (!Uri.TryCreate(value, UriKind.Absolute, out Uri? uri))
            {
                return false;
            }

            bool isLocalHost = uri.Host.Equals("127.0.0.1", StringComparison.OrdinalIgnoreCase)
                || uri.Host.Equals("localhost", StringComparison.OrdinalIgnoreCase);
            return uri.Scheme == Uri.UriSchemeHttp && isLocalHost && uri.Port == 9876;
        }
    }

    private static void PromptForDesktopShortcutIfNeeded(string appDir, string dataDir, string launcherLog)
    {
        string promptedPath = Path.Combine(dataDir, ShortcutPromptFileName);
        if (File.Exists(promptedPath))
        {
            return;
        }

        string desktopDir = Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory);
        if (string.IsNullOrWhiteSpace(desktopDir))
        {
            return;
        }

        string shortcutPath = Path.Combine(desktopDir, ShortcutName);
        if (File.Exists(shortcutPath))
        {
            MarkShortcutPrompted(promptedPath);
            return;
        }

        string? targetPath = Environment.ProcessPath;
        if (
            string.IsNullOrWhiteSpace(targetPath) ||
            !File.Exists(targetPath) ||
            !Path.GetFileName(targetPath).Equals("RutrackerChecker.exe", StringComparison.OrdinalIgnoreCase)
        )
        {
            return;
        }

        DialogResult answer = MessageBox.Show(
            "Create a desktop shortcut for RuTracker Checker?",
            "RuTracker Checker",
            MessageBoxButtons.YesNo,
            MessageBoxIcon.Question,
            MessageBoxDefaultButton.Button1
        );

        if (answer != DialogResult.Yes)
        {
            MarkShortcutPrompted(promptedPath);
            return;
        }

        try
        {
            CreateDesktopShortcut(shortcutPath, targetPath, appDir);
            MarkShortcutPrompted(promptedPath);
        }
        catch (Exception ex)
        {
            File.AppendAllText(
                launcherLog,
                $"{DateTime.Now:O} desktop shortcut failed: {ex}{Environment.NewLine}"
            );
            MessageBox.Show(
                $"Could not create the desktop shortcut:\n{ex.Message}",
                "RuTracker Checker",
                MessageBoxButtons.OK,
                MessageBoxIcon.Warning
            );
        }
    }

    private static void CreateDesktopShortcut(string shortcutPath, string targetPath, string appDir)
    {
        Type? shellType = Type.GetTypeFromProgID("WScript.Shell");
        if (shellType is null)
        {
            throw new InvalidOperationException("Windows Script Host is not available.");
        }

        object? shell = null;
        object? shortcut = null;
        try
        {
            shell = Activator.CreateInstance(shellType);
            if (shell is null)
            {
                throw new InvalidOperationException("Could not create Windows Script Host shell.");
            }

            shortcut = shellType.InvokeMember(
                "CreateShortcut",
                System.Reflection.BindingFlags.InvokeMethod,
                null,
                shell,
                [shortcutPath]
            );
            if (shortcut is null)
            {
                throw new InvalidOperationException("Could not create shortcut object.");
            }

            Type shortcutType = shortcut.GetType();
            shortcutType.InvokeMember("TargetPath", System.Reflection.BindingFlags.SetProperty, null, shortcut, [targetPath]);
            shortcutType.InvokeMember("WorkingDirectory", System.Reflection.BindingFlags.SetProperty, null, shortcut, [appDir]);
            shortcutType.InvokeMember("IconLocation", System.Reflection.BindingFlags.SetProperty, null, shortcut, [targetPath]);
            shortcutType.InvokeMember(
                "Description",
                System.Reflection.BindingFlags.SetProperty,
                null,
                shortcut,
                ["Open RuTracker Release Checker"]
            );
            shortcutType.InvokeMember("Save", System.Reflection.BindingFlags.InvokeMethod, null, shortcut, []);
        }
        finally
        {
            if (shortcut is not null && Marshal.IsComObject(shortcut))
            {
                Marshal.FinalReleaseComObject(shortcut);
            }
            if (shell is not null && Marshal.IsComObject(shell))
            {
                Marshal.FinalReleaseComObject(shell);
            }
        }
    }

    private static void MarkShortcutPrompted(string promptedPath)
    {
        try
        {
            File.WriteAllText(promptedPath, DateTime.UtcNow.ToString("O"));
        }
        catch
        {
        }
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
