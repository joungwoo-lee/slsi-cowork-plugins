using System.Runtime.InteropServices;

namespace DocCopyCli.Copiers;

/// <summary>
/// Interop-based Excel copier. Opens the file in a programmatic Excel instance,
/// then transfers sheet data through clipboard into a separate fresh Excel instance
/// that has no DRM context, and saves from there.
/// Use for non-DRM files; for DRM files prefer ExcelCopier (shell-based).
/// </summary>
public static class ExcelInteropCopier
{
    private const int XlPasteAll = -4104;

    public static void Copy(string filePath, string outputPath)
    {
        dynamic? app = null;
        dynamic? workbook = null;
        dynamic? freshApp = null;
        dynamic? newWb = null;

        using var messageFilter = OleMessageFilter.Register();

        try
        {
            Console.Error.WriteLine($"[ExcelInteropCopier] Opening workbook: {filePath}");

            var excelType = Type.GetTypeFromProgID("Excel.Application")
                ?? throw new InvalidOperationException("Excel is not installed or COM class not registered.");

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
                CorruptLoad: 0);

            Console.Error.WriteLine("[ExcelInteropCopier] Workbook opened. Transferring to fresh instance...");

            // Spin up a separate fresh Excel instance (no DRM context)
            freshApp = Activator.CreateInstance(excelType)
                ?? throw new InvalidOperationException("Failed to create fresh Excel.Application COM instance.");

            freshApp.Visible = false;
            freshApp.DisplayAlerts = false;
            freshApp.ScreenUpdating = false;
            freshApp.EnableEvents = false;

            newWb = freshApp.Workbooks.Add();

            int srcSheetCount = SafeToInt(workbook.Worksheets.Count);
            int dstSheetCount = SafeToInt(newWb.Worksheets.Count);

            for (int i = dstSheetCount; i < srcSheetCount; i++)
                newWb.Worksheets.Add(After: newWb.Worksheets[newWb.Worksheets.Count]);
            for (int i = dstSheetCount; i > srcSheetCount; i--)
            {
                try { ((dynamic)newWb.Worksheets[i]).Delete(); } catch { }
            }

            for (int i = 1; i <= srcSheetCount; i++)
            {
                try
                {
                    dynamic srcSheet = workbook.Worksheets[i];
                    dynamic dstSheet = newWb.Worksheets[i];
                    try { dstSheet.Name = srcSheet.Name; } catch { }

                    dynamic? usedRange = null;
                    try { usedRange = srcSheet.UsedRange; } catch { }

                    if (usedRange != null)
                    {
                        usedRange.Copy();
                        dstSheet.Activate();
                        dstSheet.Range("A1").PasteSpecial(XlPasteAll);
                        Console.Error.WriteLine($"[ExcelInteropCopier] Sheet {i}/{srcSheetCount}: {srcSheet.Name}");
                    }
                }
                catch (Exception ex)
                {
                    Console.Error.WriteLine($"[ExcelInteropCopier] Warning on sheet {i}: {ex.Message}");
                }
            }

            try { freshApp.CutCopyMode = false; } catch { }

            EnsureDirectory(outputPath);
            int fileFormat = Path.GetExtension(filePath).ToLowerInvariant() == ".xls" ? -4143 : 51;
            newWb.SaveAs(
                Filename: outputPath,
                FileFormat: fileFormat,
                AddToMru: false);

            Console.Error.WriteLine($"[ExcelInteropCopier] Saved: {outputPath}");
        }
        finally
        {
            try { newWb?.Close(false); } catch { }
            try { freshApp?.Quit(); } catch { }
            ReleaseComObject(ref newWb);
            ReleaseComObject(ref freshApp);
            try { workbook?.Close(false); } catch { }
            try { app?.Quit(); } catch { }
            ReleaseComObject(ref workbook);
            ReleaseComObject(ref app);
        }
    }

    private static void EnsureDirectory(string filePath)
    {
        string? dir = Path.GetDirectoryName(filePath);
        if (!string.IsNullOrEmpty(dir)) Directory.CreateDirectory(dir);
    }

    private static int SafeToInt(object? value)
    {
        try { return Convert.ToInt32(value); } catch { return 0; }
    }

    private static void ReleaseComObject<T>(ref T? obj) where T : class
    {
        if (obj == null) return;
        try { if (Marshal.IsComObject(obj)) Marshal.ReleaseComObject(obj); } catch { }
        obj = null;
    }
}
