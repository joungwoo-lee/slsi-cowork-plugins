using DocReaderCli.Readers;

namespace DocReaderCli;

class Program
{
    [STAThread]
    static int Main(string[] args)
    {
        string? filePath = null;

        // Parse --file argument
        for (int i = 0; i < args.Length; i++)
        {
            if (args[i] == "--file" && i + 1 < args.Length)
            {
                filePath = args[i + 1];
                break;
            }
        }

        if (string.IsNullOrWhiteSpace(filePath))
        {
            Console.Error.WriteLine("Usage: DocReaderCli.exe --file <path>");
            Console.Error.WriteLine("Supported formats: .docx, .doc, .pdf, .xlsx, .xls, .pptx, .ppt, .pptm, .ppsx, .pps, .potx, .potm");
            return 1;
        }

        if (!File.Exists(filePath))
        {
            Console.Error.WriteLine($"Error: File not found: {filePath}");
            return 2;
        }

        string ext = Path.GetExtension(filePath).ToLowerInvariant();

        try
        {
            string result = ext switch
            {
                ".docx" or ".doc" or ".pdf" => WordReader.Read(filePath),
                ".xlsx" or ".xls" => ExcelReader.Read(filePath),
                ".pptx" or ".ppt" or ".pptm" or ".ppsx" or ".pps" or ".potx" or ".potm" => PowerPointReader.Read(filePath),
                _ => throw new NotSupportedException($"Unsupported file extension: {ext}")
            };

            Console.Write(result);
            return 0;
        }
        catch (TimeoutException ex)
        {
            Console.Error.WriteLine($"Timeout: {ex.Message}");
            return 3;
        }
        catch (NotSupportedException ex)
        {
            Console.Error.WriteLine($"Error: {ex.Message}");
            Console.Error.WriteLine(ex.StackTrace);
            return 4;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"Fatal error: {ex.GetType().Name}: {ex.Message}");
            Console.Error.WriteLine(ex.StackTrace);
            return 99;
        }
    }
}
