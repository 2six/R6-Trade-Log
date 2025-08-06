document.addEventListener('DOMContentLoaded', () => {
  const copyButton = document.getElementById('copyButton');
  const statusDiv = document.getElementById('status');

  copyButton.addEventListener('click', () => {
    // background.js가 저장해둔 세션 데이터를 가져옴
    chrome.storage.local.get(['sessionData'], (result) => {
      if (result.sessionData && result.sessionData.uplay_token) {
        // config.json 형식에 맞게 JSON 문자열 생성
        const configString = JSON.stringify(result.sessionData, null, 2);
        
        // 클립보드에 복사
        navigator.clipboard.writeText(configString).then(() => {
          statusDiv.textContent = '✅ 클립보드에 복사되었습니다!';
          statusDiv.style.color = 'green';
        }).catch(err => {
          statusDiv.textContent = '❌ 복사에 실패했습니다.';
          statusDiv.style.color = 'red';
          console.error('복사 실패:', err);
        });
      } else {
        statusDiv.textContent = '데이터를 찾을 수 없습니다. 마켓 페이지를 새로고침 후 다시 시도해주세요.';
        statusDiv.style.color = 'orange';
      }
    });
  });
});