// SPDX-FileCopyrightText: 2026 Evan McKeown
// SPDX-License-Identifier: Apache-2.0

// This JavaScript runs locally in the browser memory
let pendingDelta = 0; // Our temporary local variable

function updateDisplay() {
  // Get references to our HTML text and our hidden form input
  const displayObj = document.getElementById('pending-display');
  const formInputObj = document.getElementById('final-delta');
  
  // Formatting: Add a plus sign to positive numbers
  if (pendingDelta > 0) {
    displayObj.innerText = "+" + pendingDelta;
    displayObj.style.color = "#4a4"; // Green for positive
  } else if (pendingDelta < 0) {
    displayObj.innerText = pendingDelta;
    displayObj.style.color = "#d44"; // Red for negative
  } else {
    displayObj.innerText = "0";
    displayObj.style.color = "inherit"; // Normal color for zero
  }
  
  // Crucially, update the hidden form field that Python will eventually read
  formInputObj.value = pendingDelta;
}

// Notice we pass an "action" string now, not an amount!
async function triggerAction(actionName) {
  try {
    // Instead of local math, we tell Python exactly which button was clicked
    const response = await fetch(window.CALCULATE_LOGIC_URL, {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      // We send both the current local state AND the specific action name
      body: JSON.stringify({
        current: pendingDelta,
        action: actionName
      })
    });
    
    // Wait for Python to calculate and send the JSON answer back
    const data = await response.json();
    
    if (data.ask_bust) {
      const isBust = confirm("Did the player bust?");
      if (isBust) { // They clicked OK
        // Do something if they busted (e.g., reset bet, end turn)
        console.log("Player is bust.");
      }
    }

    // Python sends back the mathematically validated total in the "result" field!
    pendingDelta = data.result;
    
    // Update the visual display colors and hidden form
    updateDisplay();
  } catch (error) {
    console.error("Error communicating with Python logic:", error);
    alert("Failed to calculate score. Check network connection.");
  }
}
