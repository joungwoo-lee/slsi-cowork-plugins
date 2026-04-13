using System.Text;
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

    public static void SaveWordDocument(string outputPath, WordDocumentSnapshot snapshot)
    {
        EnsureDirectory(outputPath);

        using var document = WordprocessingDocument.Create(outputPath, WordprocessingDocumentType.Document);
        var mainPart = document.AddMainDocumentPart();
        mainPart.Document = new Document(new Body());
        var body = mainPart.Document.Body!;

        if (snapshot.Paragraphs.Count == 0)
        {
            body.AppendChild(new Paragraph());
        }
        else
        {
            foreach (var paragraphSnapshot in snapshot.Paragraphs)
            {
                body.AppendChild(CreateParagraph(paragraphSnapshot));
            }
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

    private static Paragraph CreateParagraph(WordParagraphSnapshot snapshot)
    {
        var paragraph = new Paragraph();
        var paragraphProperties = CreateParagraphProperties(snapshot);
        if (paragraphProperties != null) paragraph.Append(paragraphProperties);

        foreach (var runSnapshot in snapshot.Runs)
        {
            var run = CreateRun(runSnapshot);
            if (run != null) paragraph.Append(run);
        }

        return paragraph;
    }

    private static ParagraphProperties? CreateParagraphProperties(WordParagraphSnapshot snapshot)
    {
        var justification = snapshot.Alignment switch
        {
            1 => JustificationValues.Center,
            2 => JustificationValues.Right,
            3 => JustificationValues.Both,
            _ => JustificationValues.Left,
        };

        return justification == JustificationValues.Left
            ? null
            : new ParagraphProperties(new Justification { Val = justification });
    }

    private static Run? CreateRun(WordRunSnapshot snapshot)
    {
        string sanitized = SanitizeXmlText(snapshot.Text);
        if (sanitized.Length == 0) return null;

        var run = new Run();
        var runProperties = CreateRunProperties(snapshot);
        if (runProperties != null) run.Append(runProperties);

        AppendRunContent(run, sanitized);
        return run.ChildElements.Count == 0 ? null : run;
    }

    private static RunProperties? CreateRunProperties(WordRunSnapshot snapshot)
    {
        var properties = new RunProperties();
        bool hasProperties = false;

        if (snapshot.Bold)
        {
            properties.Append(new Bold());
            hasProperties = true;
        }

        if (snapshot.Italic)
        {
            properties.Append(new Italic());
            hasProperties = true;
        }

        if (snapshot.Underline)
        {
            properties.Append(new Underline { Val = UnderlineValues.Single });
            hasProperties = true;
        }

        if (!string.IsNullOrWhiteSpace(snapshot.FontName))
        {
            properties.Append(new RunFonts
            {
                Ascii = snapshot.FontName,
                HighAnsi = snapshot.FontName,
                EastAsia = snapshot.FontName,
                ComplexScript = snapshot.FontName,
            });
            hasProperties = true;
        }

        if (snapshot.FontSize > 0)
        {
            string size = Math.Round(snapshot.FontSize * 2, MidpointRounding.AwayFromZero).ToString(System.Globalization.CultureInfo.InvariantCulture);
            properties.Append(new FontSize { Val = size });
            properties.Append(new FontSizeComplexScript { Val = size });
            hasProperties = true;
        }

        if (!string.IsNullOrWhiteSpace(snapshot.ColorHex))
        {
            properties.Append(new Color { Val = snapshot.ColorHex });
            hasProperties = true;
        }

        return hasProperties ? properties : null;
    }

    private static void AppendRunContent(Run run, string text)
    {
        var segment = new StringBuilder();

        void FlushText()
        {
            if (segment.Length == 0) return;
            run.Append(new Text(segment.ToString()) { Space = SpaceProcessingModeValues.Preserve });
            segment.Clear();
        }

        foreach (char ch in text)
        {
            switch (ch)
            {
                case '\t':
                    FlushText();
                    run.Append(new TabChar());
                    break;
                case '\v':
                case '\n':
                    FlushText();
                    run.Append(new Break());
                    break;
                default:
                    segment.Append(ch);
                    break;
            }
        }

        FlushText();
    }

    private static string SanitizeXmlText(string value)
    {
        var sb = new StringBuilder(value.Length);

        for (int i = 0; i < value.Length; i++)
        {
            char ch = value[i];
            if (char.IsHighSurrogate(ch))
            {
                if (i + 1 < value.Length && char.IsLowSurrogate(value[i + 1]))
                {
                    sb.Append(ch);
                    sb.Append(value[++i]);
                }

                continue;
            }

            if (char.IsLowSurrogate(ch)) continue;
            if (IsValidXmlChar(ch)) sb.Append(ch);
        }

        return sb.ToString();
    }

    private static bool IsValidXmlChar(char ch)
        => ch == '\t' || ch == '\n' || ch == '\r' ||
           (ch >= ' ' && ch <= '\uD7FF') ||
           (ch >= '\uE000' && ch <= '\uFFFD');
}
