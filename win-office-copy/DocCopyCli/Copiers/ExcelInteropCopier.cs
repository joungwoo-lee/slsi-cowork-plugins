using System.Runtime.InteropServices;

namespace DocCopyCli.Copiers;

/// <summary>
/// Interop-based Excel copier. Creates a new hidden Excel instance and opens the file
/// programmatically. Use for non-DRM files; for DRM files use ExcelCopier (shell-based).
/// </summary>
public static class ExcelInteropCopier
{
    public static void Copy(string filePath, string outputPath)
    {
        dynamic? app = null;
        dynamic? workbook = null;

        using var messageFilter = OleMessageFilter.Register();

        try
        {
            Console.Error.WriteLine($"[ExcelInteropCopier] Opening workbook: {filePath}");

            var excelType = Type.GetTypeFromProgID("Excel.Application")
                ?? throw new InvalidOperationException(
                    "Excel is not installed or 'Excel.Application' COM class is not registered.");

            app = Activator.CreateInstance(excelType)
                ?? throw new InvalidOperationException("Failed to create Excel.Application COM instance.");

            app.Visible = false;
            app.DisplayAlerts = false;
            app.ScreenUpdating = false;
            app.EnableEvents = false;
            app.AskToUpdateLinks = false;

            workbook = app.Workbooks.Open(
                filePath,
                UpdateLinks: 0,
                ReadOnly: true,
                IgnoreReadOnlyRecommended: true,
                AddToMru: false,
                CorruptLoad: 0 /* xlNormalLoad */);

            Console.Error.WriteLine("[ExcelInteropCopier] Workbook opened. Saving copy...");

            string? outDir = Path.GetDirectoryName(outputPath);
            if (!string.IsNullOrEmpty(outDir)) Directory.CreateDirectory(outDir);

            // SaveCopyAs saves the in-memory content to a new file without modifying the original
            workbook.SaveCopyAs(outputPath);

            Console.Error.WriteLine($"[ExcelInteropCopier] Saved: {outputPath}");
        }
        finally
        {
            try { workbook?.Close(false); } catch { }
            try { app?.Quit(); } catch { }
            ReleaseComObject(ref workbook);
            ReleaseComObject(ref app);
        }
    }

    private static void ReleaseComObject<T>(ref T? obj) where T : class
    {
        if (obj == null) return;
        try { if (Marshal.IsComObject(obj)) Marshal.ReleaseComObject(obj); } catch { }
        obj = null;
    }
}
