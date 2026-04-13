using System.Runtime.InteropServices;
using DocCopyCli.Helpers;
using DocCopyCli.Models;

namespace DocCopyCli.Copiers;

/// <summary>
/// Interop-based Excel copier. Opens the file in a programmatic Excel instance,
/// then transfers sheet data through clipboard into a separate fresh Excel instance
/// that has no DRM context, and saves from there.
/// Use for non-DRM files; for DRM files prefer ExcelCopier (shell-based).
/// </summary>
public static class ExcelInteropCopier
{
    public static void Copy(string filePath, string outputPath)
    {
        outputPath = OpenXmlSaver.NormalizeExcelOutputPath(outputPath);
        dynamic? app = null;
        dynamic? workbook = null;

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

            Console.Error.WriteLine("[ExcelInteropCopier] Workbook opened. Capturing content...");
            var workbookSnapshot = CaptureWorkbook(workbook);
            string markdownPath = MarkdownExporter.GetMarkdownPath(outputPath, filePath);
            MarkdownExporter.WriteWorkbookMarkdown(markdownPath, workbookSnapshot);
            Console.Error.WriteLine("[ExcelInteropCopier] Workbook opened. Rebuilding OOXML workbook...");

            OpenXmlSaver.SaveWorkbook(outputPath, workbookSnapshot);

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

    private static List<ExcelSheetSnapshot> CaptureWorkbook(dynamic workbook)
    {
        var result = new List<ExcelSheetSnapshot>();
        int sheetCount = SafeToInt(workbook.Worksheets?.Count);
        for (int i = 1; i <= sheetCount; i++)
        {
            try
            {
                dynamic sheet = workbook.Worksheets[i];
                string name = SafeToString(sheet.Name, $"Sheet{i}");
                result.Add(new ExcelSheetSnapshot(name, CaptureSheetRows(sheet)));
            }
            catch (Exception ex)
            {
                Console.Error.WriteLine($"[ExcelInteropCopier] Warning capturing sheet {i}: {ex.Message}");
            }
        }

        return result;
    }

    private static IReadOnlyList<IReadOnlyList<string>> CaptureSheetRows(dynamic sheet)
    {
        try
        {
            dynamic usedRange = sheet.UsedRange;
            int rowCount = SafeToInt(usedRange?.Rows?.Count);
            int colCount = SafeToInt(usedRange?.Columns?.Count);
            if (rowCount <= 0 || colCount <= 0) return [];

            object? values = null;
            try { values = usedRange.Value2; } catch { }
            if (values is object[,] matrix)
            {
                var rows = new List<IReadOnlyList<string>>(rowCount);
                for (int row = 1; row <= rowCount; row++)
                {
                    var cells = new List<string>(colCount);
                    for (int col = 1; col <= colCount; col++)
                        cells.Add(CellToString(matrix[row, col]));
                    rows.Add(TrimTrailingEmptyCells(cells));
                }

                return TrimTrailingEmptyRows(rows);
            }

            if (rowCount == 1 && colCount == 1)
                return [[CellToString(values)]];
        }
        catch { }

        return [];
    }

    private static IReadOnlyList<IReadOnlyList<string>> TrimTrailingEmptyRows(List<IReadOnlyList<string>> rows)
    {
        int count = rows.Count;
        while (count > 0 && rows[count - 1].All(string.IsNullOrEmpty)) count--;
        return count == rows.Count ? rows : rows.Take(count).ToList();
    }

    private static IReadOnlyList<string> TrimTrailingEmptyCells(List<string> cells)
    {
        int count = cells.Count;
        while (count > 0 && string.IsNullOrEmpty(cells[count - 1])) count--;
        return count == cells.Count ? cells : cells.Take(count).ToList();
    }

    private static string CellToString(object? value)
    {
        return value switch
        {
            null => string.Empty,
            double d => d.ToString(System.Globalization.CultureInfo.InvariantCulture),
            float f => f.ToString(System.Globalization.CultureInfo.InvariantCulture),
            _ => value.ToString() ?? string.Empty,
        };
    }

    private static string SafeToString(object? value, string fallback = "")
    {
        try { return value?.ToString() ?? fallback; } catch { return fallback; }
    }
}
