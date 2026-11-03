//+------------------------------------------------------------------+
//|                                           DLL_Ingest.h            |
//|                         MetaTrader 5 DLL Interface Header          |
//+------------------------------------------------------------------+
#pragma once

// Initialize DLL (resolve common files path)
// Returns true on success, false on failure
extern "C" __declspec(dllexport) bool DLL_Ingest_Init();

// Cleanup
extern "C" __declspec(dllexport) void DLL_Ingest_Deinit();

// Send file contents to Gateway
// Parameters:
//   filename  - name of JSON file in Common Files (no path needed)
//   gateway_url - full HTTP URL to POST to
//   timeout_ms - connection timeout in milliseconds
// Returns:
//   0  - success
//  -1  - DLL not initialized
//  -2  - file not found
//  -3  - file read error
//  -4  - UTF-16 to UTF-8 conversion error
//  -5  - invalid JSON
//  -6  - HTTP request error
//  -7  - HTTP response error (non-2xx status)
extern "C" __declspec(dllexport) int DLL_Ingest_Send(
    const wchar_t* filename,
    const wchar_t* gateway_url,
    int timeout_ms
);
//+------------------------------------------------------------------+