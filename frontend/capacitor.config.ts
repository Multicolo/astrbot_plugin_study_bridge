import type { CapacitorConfig } from '@capacitor/cli'

// Android 打包：cd frontend && pnpm add -D @capacitor/cli @capacitor/core @capacitor/android
//   pnpm exec cap add android && pnpm exec cap sync && pnpm exec cap open android
//
// 注意：Android 9+ 默认禁止明文 http。如果要在局域网用 http://192.168.x.x:6188，
// 需要在 AndroidManifest.xml 的 application 上加 android:usesCleartextTraffic="true"，
// 或改用 https（推荐，见 docs/DEPLOY.md 形态 C/D）。
const config: CapacitorConfig = {
  appId: 'com.studybridge.app',
  appName: '学习桥梁',
  webDir: '../web',
  server: {
    androidScheme: 'https',
    cleartext: true,
  },
  android: {
    allowMixedContent: true,
  },
}

export default config
