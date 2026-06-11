(function () {
    const input = document.getElementById("id_new_password1");
    const fill = document.getElementById("passwordStrengthFill");
    const label = document.getElementById("passwordStrengthLabel");
    if (!input || !fill || !label) {
        return;
    }

    const labels = {
        weak: "Weak",
        moderate: "Moderate",
        strong: "Strong",
        very_strong: "Very strong",
    };

    function scorePassword(password) {
        let score = 0;
        if (password.length >= 8) score += 1;
        if (password.length >= 12) score += 1;
        if (/[a-z]/.test(password) && /[A-Z]/.test(password)) score += 1;
        if (/\d/.test(password)) score += 1;
        if (/[!@#$%^&*()_+\-=\[\]{}|;:,.<>?]/.test(password)) score += 1;

        if (score <= 2) return "weak";
        if (score === 3) return "moderate";
        if (score === 4) return "strong";
        return "very_strong";
    }

    function updateStrength() {
        const value = input.value || "";
        if (!value) {
            fill.className = "password-strength-fill";
            label.textContent = "Strength: —";
            return;
        }
        const level = scorePassword(value);
        fill.className = "password-strength-fill " + level;
        label.textContent = "Strength: " + labels[level];
    }

    input.addEventListener("input", updateStrength);
    updateStrength();
})();
