/*
 * Mock profile page.
 * Tham chiếu: docs/Facebook_TDS_Mock_Full_Auto_Design_v1.3_Selenium.md §5.5, §5.6.
 */
(function () {
  "use strict";

  var config = window.__MOCK__ || {
    targetId: "unknown",
    scenario: "success",
    delayMs: 0,
    following: false,
  };

  var actionArea = document.querySelector('[data-testid="action-area"]');
  var panelArea = document.querySelector('[data-testid="panel-area"]');

  document.querySelector('[data-testid="profile-name"]').textContent = config.targetId;
  document.querySelector('[data-testid="scenario-label"]').textContent = config.scenario;

  function renderPanel(testid, title, body) {
    var section = document.createElement("section");
    section.setAttribute("data-testid", testid);
    section.className = "panel";
    section.innerHTML = "<h2>" + title + "</h2><p>" + body + "</p>";
    panelArea.appendChild(section);
  }

  function renderFollowButton() {
    var button = document.createElement("button");
    button.type = "button";
    button.className = "follow";
    button.setAttribute("data-testid", "follow-button");
    button.setAttribute("data-following", config.following ? "true" : "false");
    button.textContent = config.following ? "Đang theo dõi" : "Theo dõi";
    button.addEventListener("click", onFollowClick);
    actionArea.appendChild(button);
  }

  async function onFollowClick(event) {
    var button = event.currentTarget;
    if (button.getAttribute("data-following") === "true") {
      return;
    }
    button.disabled = true;
    try {
      // Thứ tự bắt buộc: gọi API trước, chỉ đổi DOM sau khi server đã ghi
      // follow state. Đổi data-following trước khi fetch xong sẽ khiến runner
      // đi tiếp rồi nhận VERIFICATION_FAILED — happy path thành flaky.
      var response = await fetch("/api/mock-facebook/follow", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ target_id: config.targetId }),
      });
      if (!response.ok) {
        button.setAttribute("data-follow-error", String(response.status));
        return;
      }
      button.setAttribute("data-following", "true");
      button.textContent = "Đang theo dõi";
    } catch (err) {
      button.setAttribute("data-follow-error", String(err));
    } finally {
      button.disabled = false;
    }
  }

  switch (config.scenario) {
    case "success":
    case "already_following":
      renderFollowButton();
      break;

    case "captcha":
      renderPanel("captcha-panel", "Xác minh bảo mật", "Mock CAPTCHA. Runner phải dừng.");
      break;

    case "checkpoint":
      renderPanel("checkpoint-panel", "Checkpoint", "Mock checkpoint. Runner phải dừng.");
      break;

    case "no_button":
      renderPanel("empty-panel", "Không có hành động", "Trang thiếu nút Follow.");
      break;

    case "slow_render":
      // BẮT BUỘC delay ở client bằng setTimeout, KHÔNG phải sleep phía server.
      // Nếu delay ở server thì driver.get() sẽ block hết delay rồi bộ đếm
      // timeout 5s của runner mới bắt đầu chạy — C05 sẽ đo sai thứ.
      window.setTimeout(renderFollowButton, config.delayMs || 0);
      break;

    default:
      renderPanel("error-panel", "INVALID_SCENARIO", String(config.scenario));
      break;
  }
})();
