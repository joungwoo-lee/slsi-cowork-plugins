using DocCopyCli.Copiers;

namespace DocCopyCli;

class Program
{
    private static readonly string[] SupportedExtensions =
    [
        ".docx", ".doc",
        ".xlsx", ".xls",
        ".pptx", ".ppt", ".pptm", ".ppsx", ".pps", ".potx", ".potm"
    ];

    [STAThread]
    static int Main(string[] args)
    {
        string? filePath = null;
        string? outputPath = null;
        string excelEngine = "netoffice"; // default: shell-open for DRM
        bool allMode = false;

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
                continue;
            }
            if (args[i] == "--all")
            {
                allMode = true;
            }
        }

        if (string.IsNullOrWhiteSpace(filePath))
        {
            Console.Error.WriteLine("Usage:");
            Console.Error.WriteLine("  Single file:   DocCopyCli.exe --file <path> [--output <path>]");
            Console.Error.WriteLine("  All in folder: DocCopyCli.exe --file <dir> --all [--output <dir>]");
            Console.Error.WriteLine("Optional: --excel-engine netoffice|interop  (default: netoffice)");
            Console.Error.WriteLine("Supported: .docx, .doc, .xlsx, .xls, .pptx, .ppt, .pptm, .ppsx, .pps, .potx, .potm");
            Console.Error.WriteLine();
            Console.Error.WriteLine("Saves DRM-free identical copies of Office documents.");
            Console.Error.WriteLine("Single mode: output defaults to <original_name>_copy.<ext> in the same folder.");
            Console.Error.WriteLine("--all mode:  output defaults to <input_dir>\\drm-free\\ subfolder.");
            return 1;
        }

        if (excelEngine is not ("netoffice" or "interop"))
        {
            Console.Error.WriteLine($"Error: Unsupported Excel engine '{excelEngine}'. Use 'netoffice' or 'interop'.");
            return 1;
        }

        return allMode
            ? RunAllMode(filePath, outputPath, excelEngine)
            : RunSingleMode(filePath, outputPath, excelEngine);
    }

    static int RunSingleMode(string filePath, string? outputPath, string excelEngine)
    {
        if (!File.Exists(filePath))
        {
            Console.Error.WriteLine($"Error: File not found: {filePath}");
            return 2;
        }

        if (string.IsNullOrWhiteSpace(outputPath))
        {
            string dir = Path.GetDirectoryName(Path.GetFullPath(filePath)) ?? ".";
            string name = Path.GetFileNameWithoutExtension(filePath);
            string ext = Path.GetExtension(filePath);
            outputPath = Path.Combine(dir, $"{name}_copy{ext}");
        }

        try
        {
            CopyOne(filePath, outputPath, excelEngine);
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
            return 4;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"Fatal error: {ex.GetType().Name}: {ex.Message}");
            Console.Error.WriteLine(ex.StackTrace);
            return 99;
        }
    }

    static int RunAllMode(string inputPath, string? outputDir, string excelEngine)
    {
        string searchDir = Directory.Exists(inputPath)
            ? inputPath
            : Path.GetDirectoryName(Path.GetFullPath(inputPath)) ?? ".";

        if (!Directory.Exists(searchDir))
        {
            Console.Error.WriteLine($"Error: Directory not found: {searchDir}");
            return 2;
        }

        string targetDir = string.IsNullOrWhiteSpace(outputDir)
            ? Path.Combine(searchDir, "drm-free")
            : outputDir;

        Directory.CreateDirectory(targetDir);

        var files = Directory.EnumerateFiles(searchDir)
            .Where(f => SupportedExtensions.Contains(Path.GetExtension(f).ToLowerInvariant()))
            .OrderBy(f => f)
            .ToList();

        if (files.Count == 0)
        {
            Console.Error.WriteLine($"No supported Office files found in: {searchDir}");
            return 0;
        }

        Console.Error.WriteLine($"Found {files.Count} file(s) in: {searchDir}");
        Console.Error.WriteLine($"Output folder: {targetDir}");

        int succeeded = 0;
        int failed = 0;

        foreach (string file in files)
        {
            string outFile = Path.Combine(targetDir, Path.GetFileName(file));
            Console.Error.WriteLine($"[{succeeded + failed + 1}/{files.Count}] {Path.GetFileName(file)}");
            try
            {
                CopyOne(file, outFile, excelEngine);
                Console.WriteLine(outFile);
                succeeded++;
            }
            catch (TimeoutException ex)
            {
                Console.Error.WriteLine($"  TIMEOUT: {ex.Message}");
                failed++;
            }
            catch (Exception ex)
            {
                Console.Error.WriteLine($"  FAILED: {ex.GetType().Name}: {ex.Message}");
                failed++;
            }
        }

        Console.Error.WriteLine($"Done: {succeeded} succeeded, {failed} failed.");
        return failed > 0 ? 99 : 0;
    }

    static void CopyOne(string filePath, string outputPath, string excelEngine)
    {
        string ext = Path.GetExtension(filePath).ToLowerInvariant();
        switch (ext)
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
                throw new NotSupportedException($"Unsupported file extension: {ext}");
        }
    }
}
