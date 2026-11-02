# usta

**Kendi Claude Code'unu** **Grok Bot'un bulut bilgisayarında** çalıştır; oraya neyinin gideceğine sen karar ver.

Grok Bot iyi bir yönetici: hep açık, telefondan ulaşılıyor, araştırmada ve rutinlerde güçlü. Kod yazmak için ise birçok kişi Claude Code'u tercih ediyor. usta ikisini bağlıyor. Bir Grok botu kod işini botun bilgisayarındaki Claude Code'a verir. Claude Code senin reponda yeni bir dalda çalışır, bot da sonucu sana raporlar. Push'u sen onaylarsın.

> English: [README.md](README.md)
>
> xAI ve Anthropic ile bağlantısı yoktur. usta resmi, değiştirilmemiş Claude Code'u kurar ve **senin kendi** Claude aboneliğinle giriş yapar.

## Farkı: neyin gideceğini sen seçersin

Grok Bot'un bilgisayarı **tüm botlarının ortak alanı**; oraya koyduğun her şeyi her bot okuyabilir. Bu yüzden usta *hiçbir şeyle* başlar:

- **Sadece seçtiğin gider.** Seçmediğin hiçbir hafıza klasörü, skill, agent ya da komut yüklenmez.
- **Yasak listen.** İçinde şirket, müşteri ya da kişi adı geçen satırlar silinir. Eşleşen bir markdown başlığı varsa bölümün tamamı gider.
- **İzlenecek kategoriler.** İş, sağlık, finans, aile, müşteri: bunlara benzeyen satırlar senin onayına sunulur.
- **Kişisel veri kontrolü.** E-posta, telefon, IBAN, TC kimlik ve kart numaraları (doğrulama algoritmalarıyla) işaretlenir ya da maskelenir.
- **Sırlar asla gitmez.** Token'lar ve `KEY=değer` biçimindeki değerler maskelenir. `.env`, ayar dosyaları, MCP yapılandırmaları, kancalar ve sohbet kayıtları her zaman dışarıda kalır.
- **Önce önizleme.** `build --dry-run` neyin gideceğini, neyin hangi sebeple dışarıda kaldığını ve neyin onay beklediğini gösterir. Sen onaylamadan hiçbir şey yazılmaz. Sonraki seferlerde son export'tan bu yana değişenler gösterilir.

## Nasıl çalışır

1. **Kendi bilgisayarında:** `export/usta_export.py`, `~/.claude` içinden (hafıza, skill, agent, komut) senin kurallarınla bir bundle üretir. Bu bundle'ı sana ait **özel** bir repoya koyarsın.
2. **Bulut bilgisayarda:** `bin/setup.sh` Claude Code'u kurar, bundle'ını çeker, izin verdiğin repoları klonlar ve ortam kurallarını içeren bir `CLAUDE.md` yazar.
3. **Günlük kullanımda:** bot `usta-run <repo> '<görev>'` çalıştırır. Claude Code o repoda başsız çalışır, bir dala commit atar ve kısa bir JSON sonucu döner. `git push` engellidir. `usta-push`, sen söyleyince ve sadece korumasız bir dala push eder.

## Hızlı başlangıç

En kolayı bir ajana yaptırmak: repoyu ver ve **[AGENTS.md](AGENTS.md)** dosyasını göster. Protokol ajana betikleri okutur, ne yapacaklarını sana anlattırır ve önemli her adımda senden onay ister. Kurulum iki parçalıdır:
- **Bölüm A:** Senin bilgisayarında, örneğin Claude Code ile. Bundle burada hazırlanır.
- **Bölüm B:** Grok botunun yaptığı bulut kurulumu.

## Sırlar

Bunları Grok Bot'un **Vault**'una kendin gir, asla sohbete yapıştırma:

- `CLAUDE_CODE_OAUTH_TOKEN`: kendi bilgisayarında `claude setup-token` çalıştır ve **kişisel** hesabınla giriş yap. İşveren hesabını kullanma.
- `GH_TOKEN`: fine-grained token, sadece `repos.txt`'deki repolar için, Contents **Read and write**.
- `BUNDLE_TOKEN` (isteğe bağlı): fine-grained token, sadece bundle reposu için, Contents **Read-only**.

İki ayrı GitHub token'ı gerekiyor, çünkü fine-grained token tek bir izin setini seçtiğin tüm repolara uygular. Tek token kullanırsan bundle reposuna da yazma izni vermiş olursun.

## Kullanım şartları

Anthropic'in [hukuk ve uyum sayfası](https://code.claude.com/docs/en/legal-and-compliance), değiştirilmemiş Claude Code'a kendi aboneliğinle giriş yapmana, bir platform barındırıyor olsa bile izin veriyor. Aynı sayfa şunları da söylüyor:
- Abonelik **senin** içindir; paylaşma, satma, başkalarının isteklerini onunla karşılama.
- Pro/Max limitleri **sıradan, bireysel kullanım** varsayımıyla belirlenmiştir; usta limit aşma aracı değildir.
- Üçüncü taraflar oturum token'ını toplayamaz. usta toplamaz: token'ı sen üretir, kendi Vault'una koyarsın.

Şartlar değişebilir, güncel halini kendin kontrol et.

## Güvenlik

- **Ortak bilgisayar.** Diğer botlarına Claude Code'u çağırmamalarını söyle ya da Grok'ta *Use Claude Code → Ask first* kuralını ekle.
- **Prompt injection.** `curl`, `ssh`, `git push` ve sır klasörünü okumak yasak. `npm`, `node` ve `python3` serbest, bu yüzden sadece kendi repolarını listele.
- **Çıkış ülkesi.** IP değişkendir. `usta-run` her koşudan önce ülkeyi kontrol eder, desteklenmeyen bölgede koşmaz.
- **Sıfırlanma.** Bilgisayar sıfırlanırsa `setup.sh`'ı tekrar çalıştır; betik idempotenttir.

Ayrıntılar: [SECURITY.md](SECURITY.md).

## Durum

Erken sürüm (v0.1). Export aracı ve betikler testlerle doğrulanıyor. Bilinen eksikler: uzun görev bitince botu uyandıran webhook yok, şimdilik tek Claude hesabı destekleniyor.

## Lisans

MIT
