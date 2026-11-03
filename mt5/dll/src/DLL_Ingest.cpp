//+------------------------------------------------------------------+
//|                                           DLL_Ingest.cpp          |
//|                    MT5 OHLC Data Ingest DLL (WinHTTP)              |
//+------------------------------------------------------------------+
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <winhttp.h>
#include <iostream>
#include <string>
#include <vector>

// Link against WinHTTP library
#pragma comment(lib, "winhttp.lib")

#include "DLL_Ingest.h"

// ── Global state ──────────────────────────────────────────────────────
static wchar_t g_common_files_path[MAX_PATH] = {0};
static bool    g_initialized = false;

// ── Helper: Get MetaTrader Common Files path ──────────────────────────
static bool GetCommonFilesPath(wchar_t* path, DWORD path_size)
{
    // Common Files is at: TerminalDir\Profiles\<TerminalID>\...
    // The standard location is:
    //   C:\Users\<User>\AppData\Roaming\MetaQuotes\Terminal\Common\Files
    //
    // We use SHGetFolderPath for reliability across Windows versions.
    if(SUCCEEDED(SHGetFolderPathW(NULL, CSIDL_COMMON_APPDATA, NULL, 0, path)))
    {
        wcscat_s(path, path_size, L"\\MetaQuotes\\Terminal\\Common\\Files");
        return true;
    }
    return false;
}

// ── Helper: Build full file path ──────────────────────────────────────
static bool BuildFilePath(const wchar_t* filename, wchar_t* full_path, DWORD path_size)
{
    if(!g_initialized)
        return false;

    // Copy common files path
    wcscpy_s(full_path, path_size, g_common_files_path);

    // Append folder and filename
    wcscat_s(full_path, path_size, L"\\");
    wcscat_s(full_path, path_size, filename);

    return true;
}

// ── Helper: Read file as UTF-16 ───────────────────────────────────────
static std::wstring ReadFileAsUTF16(const wchar_t* filepath)
{
    std::wstring content;

    HANDLE hFile = CreateFileW(
        filepath,
        GENERIC_READ,
        FILE_SHARE_READ,
        NULL,
        OPEN_EXISTING,
        FILE_ATTRIBUTE_NORMAL,
        NULL
    );

    if(hFile == INVALID_HANDLE_VALUE)
        return content;  // Empty string indicates failure

    DWORD fileSize = GetFileSize(hFile, NULL);
    if(fileSize == INVALID_FILE_SIZE || fileSize == 0)
    {
        CloseHandle(hFile);
        return content;
    }

    // Read file
    std::vector<char> buffer(fileSize + 2);  // +2 for null terminator
    DWORD bytesRead = 0;
    if(!ReadFile(hFile, buffer.data(), fileSize, &bytesRead, NULL))
    {
        CloseHandle(hFile);
        return content;
    }
    CloseHandle(hFile);

    // Convert to wide string (UTF-16)
    // The file is already UTF-16, so we need to handle BOM
    int offset = 0;
    if(bytesRead >= 2 && buffer[0] == '\xFF' && buffer[1] == '\xFE')
    {
        // UTF-16 LE BOM present, skip it
        offset = 2;
    }

    int wideLen = MultiByteToWideChar(CP_UTF16LE, 0, buffer.data() + offset, bytesRead - offset, NULL, 0);
    if(wideLen <= 0)
        return content;

    content.resize(wideLen);
    MultiByteToWideChar(CP_UTF16LE, 0, buffer.data() + offset, bytesRead - offset, &content[0], wideLen);

    return content;
}

// ── Helper: Convert UTF-16 to UTF-8 ───────────────────────────────────
static std::string WStringToUTF8(const std::wstring& wstr)
{
    if(wstr.empty())
        return "";

    int utf8Size = WideCharToMultiByte(
        CP_UTF8,
        0,
        wstr.c_str(),
        -1,
        NULL,
        0,
        NULL,
        NULL
    );

    if(utf8Size <= 0)
        return "";

    std::string utf8(utf8Size, '\0');
    WideCharToMultiByte(
        CP_UTF8,
        0,
        wstr.c_str(),
        -1,
        &utf8[0],
        utf8Size,
        NULL,
        NULL
    );

    // Remove trailing null
    utf8.resize(utf8Size - 1);
    return utf8;
}

// ── Helper: Validate JSON (basic check) ──────────────────────────────
static bool IsValidJSON(const std::string& json)
{
    if(json.empty())
        return false;

    // Basic validation: must start with { or [ and end with } or ]
    size_t first_non_ws = json.find_first_not_of(" \t\n\r");
    if(first_non_ws == std::string::npos)
        return false;

    char first = json[first_non_ws];
    if(first != '{' && first != '[')
        return false;

    size_t last_non_ws = json.find_last_not_of(" \t\n\r");
    char last = json[last_non_ws];
    if((first == '{' && last != '}') || (first == '[' && last != ']'))
        return false;

    return true;
}

// ── Helper: HTTP POST using WinHTTP ───────────────────────────────────
static int SendHTTPPOST(
    const wchar_t* gateway_url,
    const std::string& body,
    int timeout_ms
)
{
    // Parse URL
    URL_COMPONENTSW url_components = {0};
    wchar_t scheme[32] = {0};
    wchar_t host[256] = {0};
    wchar_t path[512] = {0};

    url_components.dwStructSize = sizeof(url_components);
    url_components.lpszScheme = scheme;
    url_components.dwSchemeLength = ARRAYSIZE(scheme);
    url_components.lpszHostName = host;
    url_components.dwHostNameLength = ARRAYSIZE(host);
    url_components.lpszUrlPath = path;
    url_components.dwUrlPathLength = ARRAYSIZE(path);

    if(!WinHttpCrackUrl(gateway_url, 0, 0, &url_components))
    {
        std::cerr << "Failed to parse URL: " << GetLastError() << std::endl;
        return -6;
    }

    // Determine port
    INTERNET_PORT port = url_components.nPort;
    if(port == 0)
    {
        port = (url_components.dwScheme == INTERNET_SCHEME_HTTPS) ? 443 : 80;
    }

    // Connect
    HINTERNET hSession = WinHttpOpen(
        L"MetaTrader5-LQ/1.0",
        WINHTTP_ACCESS_TYPE_DEFAULT_PROXY,
        WINHTTP_NO_PROXY_NAME,
        WINHTTP_NO_PROXY_BYPASS,
        0
    );

    if(!hSession)
    {
        std::cerr << "WinHttpOpen failed: " << GetLastError() << std::endl;
        return -6;
    }

    HINTERNET hConnect = WinHttpConnect(
        hSession,
        host,
        port,
        0
    );

    if(!hConnect)
    {
        std::cerr << "WinHttpConnect failed: " << GetLastError() << std::endl;
        WinHttpCloseHandle(hSession);
        return -6;
    }

    // Open request
    HINTERNET hRequest = WinHttpOpenRequest(
        hConnect,
        L"POST",
        path,
        NULL,
        WINHTTP_NO_REFERER,
        WINHTTP_DEFAULT_ACCEPT_TYPES,
        (url_components.dwScheme == INTERNET_SCHEME_HTTPS) ? WINHTTP_FLAG_SECURE : 0
    );

    if(!hRequest)
    {
        std::cerr << "WinHttpOpenRequest failed: " << GetLastError() << std::endl;
        WinHttpCloseHandle(hConnect);
        WinHttpCloseHandle(hSession);
        return -6;
    }

    // Set timeout
    DWORD timeout = (DWORD)timeout_ms;
    WinHttpSetTimeouts(hRequest, timeout, timeout, timeout, timeout);

    // Set headers
    const wchar_t* headers = L"Content-Type: application/json; charset=utf-8\r\n";

    // Send request
    DWORD contentLength = static_cast<DWORD>(body.size());
    BOOL result = WinHttpSendRequest(
        hRequest,
        headers,
        -1,
        (LPVOID)body.c_str(),
        contentLength,
        contentLength,
        0
    );

    if(!result)
    {
        std::cerr << "WinHttpSendRequest failed: " << GetLastError() << std::endl;
        WinHttpCloseHandle(hRequest);
        WinHttpCloseHandle(hConnect);
        WinHttpCloseHandle(hSession);
        return -6;
    }

    result = WinHttpReceiveResponse(hRequest, NULL);
    if(!result)
    {
        std::cerr << "WinHttpReceiveResponse failed: " << GetLastError() << std::endl;
        WinHttpCloseHandle(hRequest);
        WinHttpCloseHandle(hConnect);
        WinHttpCloseHandle(hSession);
        return -6;
    }

    // Get status code
    DWORD statusCode = 0;
    DWORD statusCodeSize = sizeof(statusCode);
    result = WinHttpQueryHeaders(
        hRequest,
        WINHTTP_QUERY_STATUS_CODE | WINHTTP_QUERY_FLAG_NUMBER,
        WINHTTP_HEADER_NAME_BY_INDEX,
        &statusCode,
        &statusCodeSize,
        WINHTTP_NO_HEADER_INDEX
    );

    if(!result)
    {
        std::cerr << "WinHttpQueryHeaders failed: " << GetLastError() << std::endl;
        WinHttpCloseHandle(hRequest);
        WinHttpCloseHandle(hConnect);
        WinHttpCloseHandle(hSession);
        return -7;
    }

    // Check for success (2xx)
    if(statusCode < 200 || statusCode >= 300)
    {
        std::cerr << "HTTP error: " << statusCode << std::endl;
        WinHttpCloseHandle(hRequest);
        WinHttpCloseHandle(hConnect);
        WinHttpCloseHandle(hSession);
        return -7;
    }

    // Read response (optional - we just need status)
    char responseBuffer[4096] = {0};
    DWORD bytesToRead = sizeof(responseBuffer) - 1;
    DWORD bytesRead = 0;

    WinHttpReadData(hRequest, responseBuffer, bytesToRead, &bytesRead);
    responseBuffer[bytesRead] = '\0';

    std::cout << "Gateway response (" << statusCode << "): " << responseBuffer << std::endl;

    // Clean up
    WinHttpCloseHandle(hRequest);
    WinHttpCloseHandle(hConnect);
    WinHttpCloseHandle(hSession);

    return 0;  // Success
}

// ── DLL Exports ───────────────────────────────────────────────────────
extern "C" __declspec(dllexport) bool DLL_Ingest_Init()
{
    if(g_initialized)
        return true;

    if(!GetCommonFilesPath(g_common_files_path, ARRAYSIZE(g_common_files_path)))
    {
        std::cerr << "Failed to get Common Files path" << std::endl;
        return false;
    }

    g_initialized = true;
    std::wcout << L"LL-Q ingest DLL initialized. Common Files: " << g_common_files_path << std::endl;
    return true;
}

extern "C" __declspec(dllexport) void DLL_Ingest_Deinit()
{
    g_initialized = false;
    memset(g_common_files_path, 0, sizeof(g_common_files_path));
}

extern "C" __declspec(dllexport) int DLL_Ingest_Send(
    const wchar_t* filename,
    const wchar_t* gateway_url,
    int timeout_ms
)
{
    if(!g_initialized)
        return -1;

    // Build full file path
    wchar_t full_path[MAX_PATH] = {0};
    if(!BuildFilePath(filename, full_path, ARRAYSIZE(full_path)))
    {
        std::cerr << "Failed to build file path" << std::endl;
        return -2;
    }

    // Read file
    std::wstring file_content = ReadFileAsUTF16(full_path);
    if(file_content.empty())
    {
        std::cerr << "Failed to read file: " << filename << std::endl;
        return -3;
    }

    // Convert to UTF-8
    std::string utf8_content = WStringToUTF8(file_content);
    if(utf8_content.empty())
    {
        std::cerr << "Failed to convert UTF-16 to UTF-8" << std::endl;
        return -4;
    }

    // Validate JSON
    if(!IsValidJSON(utf8_content))
    {
        std::cerr << "Invalid JSON in file: " << filename << std::endl;
        return -5;
    }

    // Send HTTP POST
    return SendHTTPPOST(gateway_url, utf8_content, timeout_ms);
}
//+------------------------------------------------------------------+