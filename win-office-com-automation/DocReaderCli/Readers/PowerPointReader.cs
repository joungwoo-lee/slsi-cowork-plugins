using System.Text;
using NetOffice.PowerPointApi;
using NetOffice.OfficeApi.Enums;

namespace DocReaderCli.Readers;

public static class PowerPointReader
{
    private const int DrmPollIntervalMs = 500;
    private const int DrmTimeoutMs = 15_000;

    public static string Read(string filePath)
    {
        using var watchdog = new ProcessWatchdog("POWERPNT");
        Application? app = null;
        Presentation? pres = null;

        try
        {
            app = new Application();
            // PowerPoint doesn't support Visible=false at app level in all versions,
            // so we open the file with window hidden.
            watchdog.DetectNewProcess();

            // Presentations.Open positional: FileName, ReadOnly, Untitled, WithWindow
            pres = app.Presentations.Open(
                filePath,
                NetOffice.OfficeApi.Enums.MsoTriState.msoTrue,   // ReadOnly
                NetOffice.OfficeApi.Enums.MsoTriState.msoFalse,  // Untitled
                NetOffice.OfficeApi.Enums.MsoTriState.msoFalse   // WithWindow
            );

            WaitForDrmDecryption(pres, watchdog.TimeoutMs);

            var sb = new StringBuilder();

            int slideNum = 0;
            foreach (Slide slide in pres.Slides)
            {
                slideNum++;
                sb.AppendLine($"## Slide {slideNum}");
                sb.AppendLine();

                try
                {
                    ExtractSlide(slide, sb);
                }
                catch (Exception ex)
                {
                    Console.Error.WriteLine($"[PPTReader] Error on slide {slideNum}: {ex.Message}");
                }

                sb.AppendLine();
            }

            return sb.ToString();
        }
        finally
        {
            try { pres?.Close(); } catch { }
            try { app?.Quit(); } catch { }
            try { app?.Dispose(); } catch { }
            watchdog.KillIfRunning();
        }
    }

    private static void WaitForDrmDecryption(Presentation pres, int timeoutMs)
    {
        var sw = System.Diagnostics.Stopwatch.StartNew();
        while (sw.ElapsedMilliseconds < timeoutMs)
        {
            try
            {
                if (pres.Slides.Count > 0)
                {
                    // Try to access first slide's shapes
                    var firstSlide = pres.Slides[1];
                    if (firstSlide.Shapes.Count >= 0)
                        return;
                }
            }
            catch { }

            Thread.Sleep(DrmPollIntervalMs);
        }

        // Allow empty presentations
        try
        {
            if (pres.Slides.Count == 0)
                return;
        }
        catch { }

        throw new TimeoutException(
            $"DRM decryption timed out after {timeoutMs / 1000}s.");
    }

    private static void ExtractSlide(Slide slide, StringBuilder sb)
    {
        // Extract title if present
        try
        {
            if (slide.Shapes.HasTitle == NetOffice.OfficeApi.Enums.MsoTriState.msoTrue)
            {
                var titleText = slide.Shapes.Title?.TextFrame?.TextRange?.Text;
                if (!string.IsNullOrWhiteSpace(titleText))
                {
                    sb.AppendLine($"### {titleText.Trim()}");
                    sb.AppendLine();
                }
            }
        }
        catch { }

        // Extract all text shapes
        foreach (Shape shape in slide.Shapes)
        {
            try
            {
                if (shape.HasTextFrame == MsoTriState.msoTrue)
                {
                    var text = shape.TextFrame?.TextRange?.Text;
                    if (!string.IsNullOrWhiteSpace(text))
                    {
                        // Skip if this is the title (already emitted)
                        try
                        {
                            if (slide.Shapes.HasTitle == MsoTriState.msoTrue &&
                                shape.Name == slide.Shapes.Title?.Name)
                                continue;
                        }
                        catch { }

                        sb.AppendLine(text.Trim());
                        sb.AppendLine();
                    }
                }

                // Extract text from tables in shapes
                if (shape.HasTable == MsoTriState.msoTrue)
                {
                    ExtractTable(shape.Table, sb);
                }
            }
            catch { }
        }

        // Extract notes
        try
        {
            var notes = slide.NotesPage?.Shapes;
            if (notes != null)
            {
                foreach (Shape noteShape in notes)
                {
                    try
                    {
                        if (noteShape.HasTextFrame == MsoTriState.msoTrue)
                        {
                            var noteText = noteShape.TextFrame?.TextRange?.Text;
                            if (!string.IsNullOrWhiteSpace(noteText) &&
                                noteText.Trim().Length > 1) // skip slide number placeholder
                            {
                                sb.AppendLine($"> **Note:** {noteText.Trim()}");
                                sb.AppendLine();
                            }
                        }
                    }
                    catch { }
                }
            }
        }
        catch { }
    }

    private static void ExtractTable(NetOffice.PowerPointApi.Table table, StringBuilder sb)
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
                        cellText = table.Cell(r, c).Shape.TextFrame.TextRange.Text ?? "";
                        cellText = cellText.Replace("|", "\\|").Replace("\n", " ").Replace("\r", "");
                    }
                    catch { }
                    sb.Append($" {cellText} |");
                }
                sb.AppendLine();

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
