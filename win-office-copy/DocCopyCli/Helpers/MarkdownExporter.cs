using System.Text;
using DocCopyCli.Models;

namespace DocCopyCli.Helpers;

internal static class MarkdownExporter
{
    public static string GetMarkdownPath(string outputPath, string sourceFilePath)
    {
        string outputDir = Path.GetDirectoryName(Path.GetFullPath(outputPath)) ?? ".";
        string sourceName = Path.GetFileName(sourceFilePath);
        return Path.Combine(outputDir, $"{sourceName}.md");
    }

    public static void WriteTextMarkdown(string markdownPath, string content)
    {
        EnsureDirectory(markdownPath);
        File.WriteAllText(markdownPath, NormalizeLineEndings(content).TrimEnd() + Environment.NewLine, Encoding.UTF8);
        Console.Error.WriteLine($"[MarkdownExporter] Saved: {markdownPath}");
    }

    public static void WriteWorkbookMarkdown(string markdownPath, IReadOnlyList<ExcelSheetSnapshot> sheets)
    {
        EnsureDirectory(markdownPath);

        var sb = new StringBuilder();
        for (int i = 0; i < sheets.Count; i++)
        {
            var sheet = sheets[i];
            if (i > 0) sb.AppendLine().AppendLine();

            sb.AppendLine($"# {sheet.Name}");
            sb.AppendLine();

            if (sheet.Rows.Count == 0)
            {
                sb.AppendLine("(empty sheet)");
                continue;
            }

            int columnCount = sheet.Rows.Max(static row => row.Count);
            if (columnCount == 0)
            {
                sb.AppendLine("(empty sheet)");
                continue;
            }

            var header = Enumerable.Range(1, columnCount).Select(static i => $"Column {i}").ToArray();
            sb.AppendLine("| " + string.Join(" | ", header) + " |");
            sb.AppendLine("| " + string.Join(" | ", Enumerable.Repeat("---", columnCount)) + " |");

            foreach (var row in sheet.Rows)
            {
                var cells = Enumerable.Range(0, columnCount)
                    .Select(index => index < row.Count ? EscapeCell(row[index]) : string.Empty);
                sb.AppendLine("| " + string.Join(" | ", cells) + " |");
            }
        }

        File.WriteAllText(markdownPath, sb.ToString().TrimEnd() + Environment.NewLine, Encoding.UTF8);
        Console.Error.WriteLine($"[MarkdownExporter] Saved: {markdownPath}");
    }

    public static void WritePresentationMarkdown(string markdownPath, IReadOnlyList<string> slides)
    {
        EnsureDirectory(markdownPath);

        var sb = new StringBuilder();
        for (int i = 0; i < slides.Count; i++)
        {
            if (i > 0) sb.AppendLine().AppendLine();
            sb.AppendLine($"# Slide {i + 1}");
            sb.AppendLine();
            sb.AppendLine(string.IsNullOrWhiteSpace(slides[i]) ? "(empty slide)" : NormalizeLineEndings(slides[i]).Trim());
        }

        File.WriteAllText(markdownPath, sb.ToString().TrimEnd() + Environment.NewLine, Encoding.UTF8);
        Console.Error.WriteLine($"[MarkdownExporter] Saved: {markdownPath}");
    }

    private static string EscapeCell(string value) => NormalizeLineEndings(value).Replace("|", "\\|").Replace("\n", "<br>");

    private static string NormalizeLineEndings(string value) => value.Replace("\r\n", "\n").Replace('\r', '\n');

    private static void EnsureDirectory(string filePath)
    {
        string? dir = Path.GetDirectoryName(filePath);
        if (!string.IsNullOrEmpty(dir)) Directory.CreateDirectory(dir);
    }
}
