using System.Runtime.InteropServices;

namespace DocReaderCli;

/// <summary>
/// Registers an OLE message filter on the STA thread to automatically retry
/// COM calls when Excel responds with RPC_E_SERVERCALL_RETRYLATER (0x8001010A).
/// Must be created and disposed on the same STA thread that calls Excel COM.
/// </summary>
internal sealed class OleMessageFilter : IMessageFilter, IDisposable
{
    private const int MaxRetryMs = 60_000;

    private IMessageFilter? _previousFilter;

    private OleMessageFilter() { }

    public static OleMessageFilter Register()
    {
        var filter = new OleMessageFilter();
        CoRegisterMessageFilter(filter, out filter._previousFilter);
        return filter;
    }

    public void Dispose()
    {
        CoRegisterMessageFilter(_previousFilter, out _);
        _previousFilter = null;
    }

    // Called when the server rejects our outgoing COM call.
    // dwRejectType: 0 = SERVERCALL_REJECTED, 2 = SERVERCALL_RETRYLATER
    // Return value: -1 = cancel, >= 0 = retry after N ms
    public int RetryRejectedCall(IntPtr hTaskCallee, int dwTickCount, int dwRejectType)
    {
        if (dwRejectType == 2 && dwTickCount < MaxRetryMs)
            return 500; // retry after 500 ms
        return -1; // cancel
    }

    // Called when an inbound COM call arrives while we are in an outbound call.
    // Return 0 = SERVERCALL_ISHANDLED (process it).
    public int HandleInComingCall(int dwCallType, IntPtr hTaskCaller, int dwTickCount, IntPtr lpInterfaceInfo)
        => 0;

    // Called when a Windows message arrives during an outbound COM call.
    // Return 2 = PENDINGMSG_WAITDEFPROCESS (pump messages normally).
    public int MessagePending(IntPtr hTaskCallee, int dwTickCount, int dwPendingType)
        => 2;

    [DllImport("ole32.dll")]
    private static extern void CoRegisterMessageFilter(
        IMessageFilter? newFilter,
        out IMessageFilter? oldFilter);
}

[ComImport]
[Guid("00000016-0000-0000-C000-000000000046")]
[InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
internal interface IMessageFilter
{
    [PreserveSig]
    int HandleInComingCall(int dwCallType, IntPtr hTaskCaller, int dwTickCount, IntPtr lpInterfaceInfo);

    [PreserveSig]
    int RetryRejectedCall(IntPtr hTaskCallee, int dwTickCount, int dwRejectType);

    [PreserveSig]
    int MessagePending(IntPtr hTaskCallee, int dwTickCount, int dwPendingType);
}
