/* Compile against the matching vendor HCNetSDK.h using an x64 MSVC prompt. */
#include <stdio.h>
#include <stddef.h>
#include "HCNetSDK.h"
#define SIZE(type) printf("\"" #type "\":%llu,", (unsigned long long)sizeof(type))
#define FIELD(type, field) printf("\"" #type "." #field "\":%llu,", (unsigned long long)offsetof(type, field))
int main(void) {
    printf("{");
    SIZE(BOOL); SIZE(LONG); SIZE(DWORD); SIZE(HWND);
    SIZE(NET_DVR_DEVICEINFO_V30); SIZE(NET_DVR_CLIENTINFO); SIZE(NET_DVR_JPEGPARA);
    FIELD(NET_DVR_CLIENTINFO, lChannel); FIELD(NET_DVR_CLIENTINFO, lLinkMode);
    FIELD(NET_DVR_CLIENTINFO, hPlayWnd); FIELD(NET_DVR_CLIENTINFO, sMultiCastIP);
    FIELD(NET_DVR_DEVICEINFO_V30, byStartChan);
    FIELD(NET_DVR_DEVICEINFO_V30, byStartDChan);
    FIELD(NET_DVR_DEVICEINFO_V30, byHighDChanNum);
    printf("\"NET_DVR_DEVICEINFO_V30.bySupport4\":%llu}\n", (unsigned long long)offsetof(NET_DVR_DEVICEINFO_V30, bySupport4));
    return 0;
}
