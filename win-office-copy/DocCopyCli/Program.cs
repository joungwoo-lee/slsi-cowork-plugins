using DocCopyCli.Copiers;

namespace DocCopyCli;

class Program
{
    [STAThread]
    static int Main(string[] args)
    {
        string? filePath = null;
        string? outputPath = null;
        string excelEngine = "netoffice"; // default: shell-open for DRM

        for (int i = 0; i < args.Length; i++)
        {
            if (args[i] == "--file" && i + 1 < args.Length)
            {
                filePath = args[++i];
                continue;
            }
            if (args[i] == "--output" && i + 1 < args.Length)
            {
                outputPath = args[++i];
                continue;
            }
            if (args[i] == "--excel-engine" && i + 1 < args.Length)
            {
                excelEngine = args[++i].ToLowerInvariant();
            }
        }

        if (string.IsNullOrWhiteSpace(filePath))
        {
            Console.Error.WriteLine("Usage: DocCopyCli.exe --file <path> [--output <path>]");
            Console.Error.WriteLine("Optional: --excel-engine netoffice|interop  (default: netoffice)");
            Console.Error.WriteLine("Supported: .docx, .doc, .xlsx, .xls, .pptx, .ppt, .pptm, .ppsx, .pps, .potx, .potm");
            Console.Error.WriteLine();
            Console.Error.WriteLine("Saves a DRM-free identical copy of the document.");
            Console.Error.WriteLine("If --output is omitted, saves as <original_name>_copy.<ext> in the same folder.");
            return 1;
        }

        if (excelEngine is not ("netoffice" or "interop"))
        {
            Console.Error.WriteLine($"Error: Unsupported Excel engine '{excelEngine}'. Use 'netoffice' or 'interop'.");
            return 1;
        }

        if (!File.Exists(filePath))
        {
            Console.Error.WriteLine($"Error: File not found: {filePath}");
            return 2;
        }

        // Auto-generate output path if not specified
        if (string.IsNullOrWhiteSpace(outputPath))
        {
            string dir = Path.GetDirectoryName(Path.GetFullPath(filePath)) ?? ".";
            string name = Path.GetFileNameWithoutExtension(filePath);
            string ext = Path.GetExtension(filePath);
            outputPath = Path.Combine(dir, $"{name}_copy{ext}");
        }

        string inputExt = Path.GetExtension(filePath).ToLowerInvariant();

        try
        {
            switch (inputExt)
            {
                case ".docx":
                case ".doc":
                    WordCopier.Copy(filePath, outputPath);
                    break;

                case ".xlsx":
                case ".xls":
                    if (excelEngine == "interop")
                        ExcelInteropCopier.Copy(filePath, outputPath);
                    else
                        ExcelCopier.Copy(filePath, outputPath);
                    break;

                case ".pptx":
                case ".ppt":
                case ".pptm":
                case ".ppsx":
                case ".pps":
                case ".potx":
                case ".potm":
                    PowerPointCopier.Copy(filePath, outputPath);
                    break;

                default:
                    Console.Error.WriteLine($"Error: Unsupported file extension: {inputExt}");
                    return 4;
            }

            Console.WriteLine(outputPath);
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
