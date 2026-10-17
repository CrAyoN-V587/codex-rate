// Read-only navigation metadata. Never invokes, focuses, or edits a control.
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;
using System.Windows.Automation;

class ActiveConversation
{
    delegate bool EnumProc(IntPtr hwnd, IntPtr unused);
    [DllImport("user32.dll")] static extern bool EnumWindows(EnumProc callback, IntPtr unused);
    [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr hwnd);
    [DllImport("user32.dll")] static extern bool IsIconic(IntPtr hwnd);
    [DllImport("user32.dll")] static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint pid);
    [DllImport("kernel32.dll")] static extern IntPtr OpenProcess(uint access, bool inherit, uint pid);
    [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr handle);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode)]
    static extern int GetPackageFamilyName(IntPtr process, ref uint length, StringBuilder name);
    [DllImport("UIAutomationCore.dll")]
    static extern int UiaGetPropertyValue(IntPtr node, int property, [MarshalAs(UnmanagedType.Struct)] out object value);

    static IntPtr previous = IntPtr.Zero;
    static readonly JavaScriptSerializer Json = new JavaScriptSerializer();

    static bool IsCodex(IntPtr hwnd)
    {
        uint pid;
        GetWindowThreadProcessId(hwnd, out pid);
        IntPtr process = OpenProcess(0x1000, false, pid);
        if (process == IntPtr.Zero) return false;
        try
        {
            uint length = 256;
            StringBuilder family = new StringBuilder((int)length);
            return GetPackageFamilyName(process, ref length, family) == 0 &&
                family.ToString().StartsWith("OpenAI.Codex_");
        }
        finally { CloseHandle(process); }
    }

    static IntPtr Window()
    {
        IntPtr foreground = GetForegroundWindow();
        List<IntPtr> windows = new List<IntPtr>();
        EnumWindows(delegate(IntPtr hwnd, IntPtr unused)
        {
            if (IsWindowVisible(hwnd) && !IsIconic(hwnd) && IsCodex(hwnd)) windows.Add(hwnd);
            return true;
        }, IntPtr.Zero);
        if (windows.Contains(foreground)) previous = foreground;
        else if (!windows.Contains(previous)) previous = windows.Count == 1 ? windows[0] : IntPtr.Zero;
        return previous;
    }

    static string Aria(AutomationElement element)
    {
        // .NET Framework's UIA wrapper predates AriaProperties (30102).
        // Its safe HUIANODE can be queried through the native read-only API.
        foreach (var field in typeof(AutomationElement).GetFields(
            System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance))
        {
            SafeHandle handle = field.GetValue(element) as SafeHandle;
            if (handle == null || handle.IsInvalid || handle.IsClosed) continue;
            object value;
            if (UiaGetPropertyValue(handle.DangerousGetHandle(), 30102, out value) >= 0)
                return value as string;
        }
        return null;
    }

    static object Read()
    {
        IntPtr hwnd = Window();
        if (hwnd == IntPtr.Zero) return new { window = 0, titles = new string[0], error = "no-codex-window" };
        AutomationElement root = AutomationElement.FromHandle(hwnd);
        var condition = new OrCondition(
            new PropertyCondition(AutomationElement.ControlTypeProperty, ControlType.Button),
            new PropertyCondition(AutomationElement.ControlTypeProperty, ControlType.Hyperlink),
            new PropertyCondition(AutomationElement.ControlTypeProperty, ControlType.TreeItem));
        var controls = root.FindAll(TreeScope.Descendants, condition);
        HashSet<string> titles = new HashSet<string>();
        foreach (AutomationElement control in controls)
        {
            if ((bool)control.GetCurrentPropertyValue(AutomationElement.IsOffscreenProperty)) continue;
            string aria = Aria(control);
            if (String.IsNullOrEmpty(aria)) continue;
            bool current = false;
            foreach (string property in aria.Split(';'))
                if (property.Trim() == "current=page") current = true;
            if (!current) continue;
            string title = control.Current.Name;
            if (!String.IsNullOrWhiteSpace(title)) titles.Add(title);
        }
        return new { window = hwnd.ToInt64(), titles = new List<string>(titles), error = (string)null };
    }

    [STAThread]
    static void Main(string[] args)
    {
        Console.OutputEncoding = new UTF8Encoding(false);
        bool once = Array.IndexOf(args, "--once") >= 0;
        do
        {
            try { Console.WriteLine(Json.Serialize(Read())); }
            catch (Exception error)
            {
                Console.WriteLine(Json.Serialize(new { window = 0, titles = new string[0], error = error.GetType().Name }));
            }
            if (!once) Thread.Sleep(200);
        } while (!once);
    }
}
