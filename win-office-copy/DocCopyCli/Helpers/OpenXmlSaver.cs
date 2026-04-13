using ClosedXML.Excel;
using DocCopyCli.Models;
using DocumentFormat.OpenXml;
using DocumentFormat.OpenXml.Packaging;
using DocumentFormat.OpenXml.Wordprocessing;

namespace DocCopyCli.Helpers;

internal static class OpenXmlSaver
{
    public static string NormalizeWordOutputPath(string outputPath)
        => Path.ChangeExtension(outputPath, ".docx");

    public static string NormalizeExcelOutputPath(string outputPath)
        => Path.ChangeExtension(outputPath, ".xlsx");

    public static void SaveWordDocument(string outputPath, string textContent)
    {
        EnsureDirectory(outputPath);

        using var document = WordprocessingDocument.Create(outputPath, WordprocessingDocumentType.Document);
        var mainPart = document.AddMainDocumentPart();
        mainPart.Document = new Document(new Body());
        var body = mainPart.Document.Body!;

        var normalized = textContent.Replace("\r\n", "\n").Replace('\r', '\n');
        foreach (string paragraphText in normalized.Split('\n'))
        {
            body.AppendChild(new Paragraph(new Run(new Text(paragraphText) { Space = SpaceProcessingModeValues.Preserve })));
        }

        mainPart.Document.Save();
        Console.Error.WriteLine($"[OpenXmlSaver] Saved Word document: {outputPath}");
    }

    public static void SaveWorkbook(string outputPath, IReadOnlyList<ExcelSheetSnapshot> sheets)
    {
        EnsureDirectory(outputPath);

        using var workbook = new XLWorkbook();
        bool addedSheet = false;

        foreach (var sheet in sheets)
        {
            string name = SanitizeSheetName(sheet.Name, workbook.Worksheets.Select(ws => ws.Name).ToHashSet(StringComparer.OrdinalIgnoreCase));
            var ws = workbook.Worksheets.Add(name);
            addedSheet = true;

            for (int rowIndex = 0; rowIndex < sheet.Rows.Count; rowIndex++)
            {
                var row = sheet.Rows[rowIndex];
                for (int colIndex = 0; colIndex < row.Count; colIndex++)
                {
                    ws.Cell(rowIndex + 1, colIndex + 1).Value = row[colIndex];
                }
            }

            if (sheet.Rows.Count > 0)
            {
                ws.Columns().AdjustToContents();
            }
        }

        if (!addedSheet)
        {
            workbook.Worksheets.Add("Sheet1");
        }

        workbook.SaveAs(outputPath);
        Console.Error.WriteLine($"[OpenXmlSaver] Saved Excel workbook: {outputPath}");
    }

    private static string SanitizeSheetName(string? name, HashSet<string> existingNames)
    {
        string cleaned = string.IsNullOrWhiteSpace(name) ? "Sheet" : name;
        foreach (char invalid in new[] { ':', '\\', '/', '?', '*', '[', ']' })
            cleaned = cleaned.Replace(invalid, '_');

        cleaned = cleaned.Trim();
        if (cleaned.Length == 0) cleaned = "Sheet";
        if (cleaned.Length > 31) cleaned = cleaned[..31];

        string candidate = cleaned;
        int suffix = 2;
        while (existingNames.Contains(candidate))
        {
            string tail = $"_{suffix++}";
            int maxBaseLength = Math.Max(1, 31 - tail.Length);
            candidate = cleaned[..Math.Min(cleaned.Length, maxBaseLength)] + tail;
        }

        existingNames.Add(candidate);
        return candidate;
    }

    private static void EnsureDirectory(string filePath)
    {
        string? dir = Path.GetDirectoryName(filePath);
        if (!string.IsNullOrEmpty(dir)) Directory.CreateDirectory(dir);
    }
}
