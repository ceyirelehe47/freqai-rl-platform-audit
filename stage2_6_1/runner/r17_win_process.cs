// Process identity and termination operate on ONE opened native handle.
// This helper never enumerates processes and never terminates by name.
using System;
using System.Diagnostics;
using System.Runtime.InteropServices;
namespace R17Sampler {
    public sealed class Reply {
        public string Status;
        public bool NativeExited;
        public bool IdentityMatched;
        public bool Forced;
        public string ActualCreation;
        public int Error;
    }
    public static class Native {
        [StructLayout(LayoutKind.Sequential)]
        private struct FT { public uint Low; public uint High; }
        [DllImport("kernel32.dll", SetLastError=true)]
        private static extern IntPtr OpenProcess(uint access, bool inherit, int pid);
        [DllImport("kernel32.dll", SetLastError=true)]
        private static extern bool GetProcessTimes(IntPtr h, out FT c, out FT e, out FT k, out FT u);
        [DllImport("kernel32.dll", SetLastError=true)]
        private static extern uint WaitForSingleObject(IntPtr h, uint timeout);
        [DllImport("kernel32.dll", SetLastError=true)]
        private static extern bool TerminateProcess(IntPtr h, uint code);
        [DllImport("kernel32.dll")]
        private static extern bool CloseHandle(IntPtr h);
        [DllImport("kernel32.dll")]
        private static extern IntPtr GetCurrentProcess();
        private static ulong Creation(IntPtr h) {
            FT c,e,k,u;
            if (!GetProcessTimes(h, out c, out e, out k, out u))
                throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
            return ((ulong)c.High << 32) | c.Low;
        }
        public static string CurrentCreation() {
            return Creation(GetCurrentProcess()).ToString(System.Globalization.CultureInfo.InvariantCulture);
        }
        private static int Remaining(Stopwatch clock, int budgetMs, DateTime expires) {
            double wall = (expires - DateTime.UtcNow).TotalMilliseconds;
            return (int)Math.Max(0, Math.Min(budgetMs - clock.Elapsed.TotalMilliseconds, wall));
        }
        public static Reply Stop(int pid, string creation, int cooperateMs,
                                 int forceWaitMs, int budgetMs, string expiresUtc) {
            var r = new Reply { Status="unconfirmed", ActualCreation="" };
            var clock = Stopwatch.StartNew();
            DateTime expires = DateTime.Parse(expiresUtc, System.Globalization.CultureInfo.InvariantCulture,
                System.Globalization.DateTimeStyles.AssumeUniversal | System.Globalization.DateTimeStyles.AdjustToUniversal);
            ulong expected;
            if (pid <= 0 || !UInt64.TryParse(creation, out expected) || expected == 0 ||
                budgetMs < 0 || cooperateMs < 0 || forceWaitMs < 0) {
                r.Status="invalid_request"; return r;
            }
            if (Remaining(clock,budgetMs,expires) <= 0) { r.Status="deadline_expired"; return r; }
            // SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_TERMINATE
            IntPtr h = OpenProcess(0x00101001, false, pid);
            if (h == IntPtr.Zero) {
                r.Error = Marshal.GetLastWin32Error();
                // Only ERROR_INVALID_PARAMETER proves no PID exists. Access denied is UNKNOWN.
                if (r.Error == 87) { r.Status="absent"; r.NativeExited=true; }
                else { r.Status="open_failed"; }
                return r;
            }
            try {
                ulong actual = Creation(h);
                r.ActualCreation = actual.ToString(System.Globalization.CultureInfo.InvariantCulture);
                if (actual != expected) {
                    // PID reuse proves the OLD instance ended; NEVER kill the new instance.
                    r.Status="pid_reused"; r.NativeExited=true; return r;
                }
                r.IdentityMatched = true;
                uint w = WaitForSingleObject(h, (uint)Math.Min(cooperateMs,Remaining(clock,budgetMs,expires)));
                if (w == 0) { r.Status="exited"; r.NativeExited=true; return r; }
                if (w != 258) { r.Status="wait_failed"; r.Error=Marshal.GetLastWin32Error(); return r; }
                if (Remaining(clock,budgetMs,expires) <= 0 || forceWaitMs == 0) {
                    r.Status="deadline_expired"; return r;
                }
                if (!TerminateProcess(h, 137)) {
                    r.Error=Marshal.GetLastWin32Error();
                    // It may have exited between wait and terminate. The SAME handle decides.
                    if (WaitForSingleObject(h,0) == 0) { r.Status="exited"; r.NativeExited=true; }
                    else { r.Status="terminate_failed"; }
                    return r;
                }
                r.Forced=true;
                w = WaitForSingleObject(h,(uint)Math.Min(forceWaitMs,Remaining(clock,budgetMs,expires)));
                if (w == 0) { r.Status="forced_exited"; r.NativeExited=true; }
                else { r.Status=w == 258 ? "force_timeout" : "wait_failed"; r.Error=Marshal.GetLastWin32Error(); }
                return r;
            } catch (System.ComponentModel.Win32Exception ex) {
                r.Status="query_failed"; r.Error=ex.NativeErrorCode; return r;
            } finally { CloseHandle(h); }
        }
    }
}
