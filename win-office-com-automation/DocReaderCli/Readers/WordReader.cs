using System.Text;
using NetOffice.WordApi;
using NetOffice.WordApi.Enums;

namespace DocReaderCli.Readers;

public static class WordReader
{
    private const int DrmPollIntervalMs = 500;
    private const int DrmTimeoutMs = 15_000;

    public static string Read(string filePath)
    {
        using var watchdog = new ProcessWatchdog("WINWORD");
        Application? app = null;
        Document? doc = null;

        try
        {
            app = new Application { Visible = false };
            app.DisplayAlerts = WdAlertLevel.wdAlertsNone;
            watchdog.DetectNewProcess();

            doc = app.Documents.Open(
                FileName: filePath,
                ReadOnly: true,
                AddToRecentFiles: false,
                Visible: false
            );

            WaitForDrmDecryption(doc, watchdog.TimeoutMs);

            var sb = new StringBuilder();
            ExtractContent(doc, sb);
            return sb.ToString();
        }
        finally
        {
            try { doc?.Close(SaveChanges: false); } catch { }
            try { app?.Quit(); } catch { }
            try { app?.Dispose(); } catch { }
            watchdog.KillIfRunning();
        }
    }

    private static void WaitForDrmDecryption(Document doc, int timeoutMs)
    {
        var sw = System.Diagnostics.Stopwatch.StartNew();
        while (sw.ElapsedMilliseconds < timeoutMs)
        {
            try
            {
                var range = doc.Content;
                if (range != null && range.Text != null && range.Text.Trim().Length > 0)
                    return;
            }
            catch { }

            Thread.Sleep(DrmPollIntervalMs);
        }

        // Allow empty documents to pass (the file opened but has no content)
        try
        {
            if (doc.Content?.Text?.Trim().Length == 0)
                return;
        }
        catch { }

        throw new TimeoutException(
            $"DRM decryption timed out after {timeoutMs / 1000}s. The document may require manual DRM authentication.");
    }

    private static void ExtractContent(Document doc, StringBuilder sb)
    {
        int tableIdx = 0;
        var tableRanges = new List<(int Start, int End)>();

        // Pre-collect table ranges to avoid duplicating table text in paragraphs
        foreach (Table table in doc.Tables)
        {
            try
            {
                var r = table.Range;
                if (r != null)
                    tableRanges.Add((r.Start, r.End));
            }
            catch { }
        }

        // Walk paragraphs in document order
        foreach (Paragraph para in doc.Paragraphs)
        {
            try
            {
                var range = para.Range;
                if (range == null) continue;

                int paraStart = range.Start;

                // Check if this paragraph is inside a table
                bool inTable = tableRanges.Any(t => paraStart >= t.Start && paraStart <= t.End);
                if (inTable)
                {
                    // Emit table at first encounter
                    var matchedTable = tableRanges.FindIndex(t => paraStart >= t.Start && paraStart <= t.End);
                    if (matchedTable >= 0 && matchedTable == tableIdx)
                    {
                        EmitTable(doc.Tables[tableIdx + 1], sb); // 1-based index
                        tableIdx++;
                    }
                    continue;
                }

                string text = range.Text?.TrimEnd('\r', '\n', '\a') ?? "";
                if (string.IsNullOrWhiteSpace(text)) continue;

                string styleName = "";
                try { styleName = ((Style)para.Style).NameLocal ?? ""; } catch { }

                if (styleName.Contains("Heading 1", StringComparison.OrdinalIgnoreCase))
                    sb.AppendLine($"# {text}");
                else if (styleName.Contains("Heading 2", StringComparison.OrdinalIgnoreCase))
                    sb.AppendLine($"## {text}");
                else if (styleName.Contains("Heading 3", StringComparison.OrdinalIgnoreCase))
                    sb.AppendLine($"### {text}");
                else if (styleName.Contains("Heading", StringComparison.OrdinalIgnoreCase))
                    sb.AppendLine($"#### {text}");
                else
                    sb.AppendLine(text);

                sb.AppendLine();
            }
            catch { }
        }

        // Emit any remaining tables not yet emitted
        for (int i = tableIdx; i < doc.Tables.Count; i++)
        {
            try { EmitTable(doc.Tables[i + 1], sb); } catch { }
        }
    }

    private static void EmitTable(Table table, StringBuilder sb)
    {
        try
        {
            int rows = table.Rows.Count;
            int cols = table.Columns.Count;

            sb.AppendLine();
            for (int r = 1; r <= rows; r++)
            {
                sb.Append("|");
                for (int c = 1; c <= cols; c++)
                {
                    string cellText = "";
                    try
                    {
                        cellText = table.Cell(r, c).Range.Text?
                            .TrimEnd('\r', '\n', '\a', '\x07') ?? "";
                    }
                    catch { }
                    sb.Append($" {cellText} |");
                }
                sb.AppendLine();

                // Header separator after first row
                if (r == 1)
                {
                    sb.Append("|");
                    for (int c = 0; c < cols; c++)
                        sb.Append(" --- |");
                    sb.AppendLine();
                }
            }
            sb.AppendLine();
        }
        catch { }
    }
}
