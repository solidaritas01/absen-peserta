document.addEventListener('DOMContentLoaded', () => {
    loadAdminSettings();
    loadAdminData();
    loadPendingUsers();
    loadActiveUsers();

    // Real-time updates: refresh data every 5 seconds without page reload
    setInterval(() => {
        loadAdminData();
        loadPendingUsers();
        loadActiveUsers();
    }, 5000);

    document.getElementById('form-settings').addEventListener('submit', async (e) => {
        e.preventDefault();
        const formData = new FormData();
        formData.append('activity_name', document.getElementById('input-activity-name').value);
        formData.append('activity_schedule', document.getElementById('input-activity-schedule').value);
        formData.append('theme_type', document.getElementById('input-theme-type').value);
        formData.append('theme_color_1', document.getElementById('input-theme-color1').value);
        formData.append('theme_color_2', document.getElementById('input-theme-color2').value);
        formData.append('theme_preset', document.getElementById('input-theme-preset').value);
        formData.append('theme_animation', document.getElementById('input-theme-animation').value);
        
        const logoFiles = document.getElementById('input-activity-logo').files;
        for (let i = 0; i < logoFiles.length; i++) {
            formData.append('activity_logos', logoFiles[i]);
        }

        const response = await fetch('/api/settings', {
            method: 'POST',
            body: formData
        });

        if (response.ok) {
            alert('Pengaturan berhasil diperbarui!');
            loadAdminSettings(); // Refresh settings without reloading the entire page
            // Refresh QR code and logos display if needed
            document.getElementById('qr-code-img').src = '/api/qrcode?' + new Date().getTime();
        }
    });
});

async function loadAdminSettings() {
    const response = await fetch('/api/settings');
    const data = await response.json();
    
    document.getElementById('input-activity-name').value = data.activity_name;
    document.getElementById('input-activity-schedule').value = data.activity_schedule;
    
    document.getElementById('input-theme-type').value = data.theme_type;
    document.getElementById('input-theme-color1').value = data.theme_color_1;
    document.getElementById('input-theme-color2').value = data.theme_color_2;
    document.getElementById('input-theme-preset').value = data.theme_preset;
    document.getElementById('input-theme-animation').value = data.theme_animation || 'flow';
    
    toggleThemeOptions();
    applyTheme(data);
}

function toggleThemeOptions() {
    const type = document.getElementById('input-theme-type').value;
    const customColors = document.getElementById('theme-custom-colors');
    const color2Group = document.getElementById('group-color2');
    const presets = document.getElementById('theme-presets');
    const animStyle = document.getElementById('theme-animation-style');

    if (type === 'preset') {
        customColors.style.display = 'none';
        presets.style.display = 'block';
        animStyle.style.display = 'none';
    } else {
        customColors.style.display = 'grid';
        presets.style.display = 'none';
        color2Group.style.display = (type === 'solid') ? 'none' : 'block';
        animStyle.style.display = (type === 'gradient_animated') ? 'block' : 'none';
    }
}

function applyTheme(data) {
    document.body.className = ''; // Reset
    const c1 = data.theme_color_1 || '#4f46e5';
    const c2 = data.theme_color_2 || '#06b6d4';
    const type = data.theme_type || 'gradient_animated';
    const preset = data.theme_preset || 'ocean';
    const anim = data.theme_animation || 'flow';

    document.body.style.setProperty('--theme-color-1', c1);
    document.body.style.setProperty('--theme-color-2', c2);
    
    if (type === 'preset') {
        document.body.classList.add(`theme-${preset}`);
    } else {
        document.body.classList.add(`theme-${type}`);
        if (type === 'gradient_animated') {
            document.body.classList.add(`anim-${anim}`);
        }
    }
}

async function loadAdminData() {
    const response = await fetch('/api/participants');
    const participants = await response.json();
    
    const tbody = document.getElementById('tbody-participants');
    tbody.innerHTML = '';
    
    let total = participants.length;
    let hadir = 0;
    let izin = 0;
    let belum = 0;

    participants.forEach(p => {
        const tr = document.createElement('tr');
        
        let statusBadge = '';
        if (p.status === 'Hadir' || p.status === 'Tepat Waktu') {
            statusBadge = `<span class="badge badge-present">Hadir</span>`;
            hadir++;
        } else if (p.status === 'Terlambat') {
            statusBadge = `<span class="badge badge-late">Terlambat</span>`;
            hadir++;
        } else if (p.status === 'Izin') {
            statusBadge = `<span class="badge badge-permission">Izin</span>`;
            izin++;
        } else {
            statusBadge = `<span class="badge badge-absent">Belum Hadir</span>`;
            belum++;
        }

        tr.innerHTML = `
            <td>${p.name}</td>
            <td>${statusBadge}</td>
            <td>${p.attendance_time || '-'}</td>
            <td>${p.delay_time ? `<span style="color: var(--danger)">${p.delay_time}</span>` : '-'}</td>
            <td>${p.permission_reason || '-'}</td>
        `;
        tbody.appendChild(tr);
    });

    document.getElementById('stat-total').textContent = total;
    document.getElementById('stat-hadir').textContent = hadir;
    document.getElementById('stat-izin').textContent = izin;
    document.getElementById('stat-belum').textContent = belum;
}

async function importExcel() {
    const fileInput = document.getElementById('input-import-excel');
    if (!fileInput.files[0]) {
        alert('Pilih file Excel terlebih dahulu!');
        return;
    }

    const formData = new FormData();
    formData.append('file', fileInput.files[0]);

    const response = await fetch('/api/participants/import', {
        method: 'POST',
        body: formData
    });

    if (response.ok) {
        alert('Data berhasil diimport!');
        loadAdminData();
    } else {
        alert('Gagal mengimport data.');
    }
}

function exportExcel() {
    window.location.href = '/api/export';
}

async function resetData() {
    if (confirm('Apakah anda yakin ingin mereset data kehadiran peserta?')) {
        const response = await fetch('/api/participants/reset', { method: 'POST' });
        if (response.ok) {
            alert('Data kehadiran berhasil direset.');
            loadAdminData();
        }
    }
}
async function resetLogos() {
    if (confirm('Apakah anda yakin ingin menghapus SEMUA logo?')) {
        const response = await fetch('/api/logos/reset', { method: 'POST' });
        if (response.ok) {
            alert('Logo berhasil direset.');
            loadAdminSettings();
        }
    }
}
async function loadPendingUsers() {
    const tbody = document.getElementById('tbody-pending');
    if (!tbody) return; // Not admin

    try {
        const response = await fetch('/api/pending-users');
        const users = await response.json();
        
        if (users.length === 0) {
            tbody.innerHTML = '<tr><td colspan="4" style="text-align:center; color:var(--text-muted);">Tidak ada pendaftar baru</td></tr>';
            return;
        }

        tbody.innerHTML = users.map(u => `
            <tr>
                <td>${u.full_name}</td>
                <td>${u.username}</td>
                <td>${u.phone_number}</td>
                <td>
                    <button class="btn btn-secondary" onclick="sendWACode('${u.phone_number}', '${u.verification_code}', '${u.full_name}', '${u.username}', '${u.raw_password}')" style="padding: 0.5rem 1rem; font-size: 0.8rem; background: #25d366; border: none;">
                        <i class="fab fa-whatsapp"></i> Kirim Kode WA
                    </button>
                </td>
            </tr>
        `).join('');
    } catch (err) {
        console.error('Error loading pending users:', err);
    }
}

function sendWACode(phone, code, name, username, password) {
    const message = `Halo *${name}*,\n\nTerima kasih telah mendaftar di Sistem Absensi.\n\nBerikut adalah detail akun Anda:\n- *Username*: ${username}\n- *Password*: ${password}\n\n*KODE VERIFIKASI*: *${code}*\n\nSilakan masukkan kode tersebut di halaman verifikasi untuk mengaktifkan akun Anda. Terima kasih!`;
    const waUrl = `https://wa.me/${phone.replace(/[^0-9]/g, '')}?text=${encodeURIComponent(message)}`;
    window.open(waUrl, '_blank');
}

async function loadActiveUsers() {
    const tbody = document.getElementById('tbody-active-users');
    if (!tbody) return;

    try {
        const response = await fetch('/api/active-users');
        const users = await response.json();
        
        if (users.length === 0) {
            tbody.innerHTML = '<tr><td colspan="4" style="text-align:center; color:var(--text-muted);">Tidak ada pengguna aktif</td></tr>';
            return;
        }

        tbody.innerHTML = users.map(u => `
            <tr>
                <td>${u.full_name}</td>
                <td>${u.username}</td>
                <td>${u.last_login ? new Date(u.last_login).toLocaleString('id-ID') : 'Belum pernah'}</td>
                <td>
                    <button class="btn btn-danger" onclick="banUser(${u.id}, '${u.full_name}')" style="padding: 0.5rem 1rem; font-size: 0.8rem;">
                        <i class="fas fa-ban"></i> Banned User
                    </button>
                </td>
            </tr>
        `).join('');
    } catch (err) {
        console.error('Error loading active users:', err);
    }
}

async function banUser(id, name) {
    if (confirm(`Apakah Anda yakin ingin me-MEM-BANNED akun ${name}? Pengguna tidak akan bisa login lagi.`)) {
        const response = await fetch('/api/admin/ban', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id })
        });
        if (response.ok) {
            alert(`Akun ${name} telah berhasil di-banned.`);
            loadActiveUsers();
        }
    }
}
