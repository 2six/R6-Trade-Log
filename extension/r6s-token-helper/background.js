// 이 스크립트가 시작될 때 바로 실행되는 "생존 신호"
console.log("Service Worker started! Now listening for web requests...");

chrome.webRequest.onBeforeSendHeaders.addListener(
  (details) => {
    // 우리가 목표로 하는 graphql API 요청인지 확인
    if (details.url.includes("graphql")) {
      console.log("GraphQL request detected!", details.url); // 요청 감지 로그 추가!
      let sessionData = {};
      
      for (const header of details.requestHeaders) {
        const headerName = header.name.toLowerCase();
        if (headerName === 'authorization') {
          sessionData.uplay_token = header.value;
        } else if (headerName === 'ubi-sessionid') {
          sessionData.ubi_session_id = header.value;
        }
      }

      if (sessionData.uplay_token && sessionData.ubi_session_id) {
        chrome.storage.local.set({ sessionData: sessionData }).then(() => {
            console.log("R6S 세션 데이터를 성공적으로 저장했습니다.", sessionData);
        });
      }
    }
  },
  { urls: ["*://*.ubi.com/*"] },
  ["requestHeaders"]
);