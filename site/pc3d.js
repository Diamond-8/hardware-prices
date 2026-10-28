/*
 * بيسي ثلاثي الأبعاد واقعي بإضاءة RGB في خلفية الموقع
 * كيس بغرفتين وزجاج بدون عمود، مراوح بإطار RGB ومرآة لانهائية،
 * مبرد مائي، رامات بيضاء، كرت شاشة أفقي، وتوهج حقيقي حول الإضاءة.
 * مبني بالكود بالكامل باستخدام مكتبة three.js
 */
(function () {
  "use strict";
  if (!window.THREE) return;
  const canvas = document.getElementById("pc3d");
  if (!canvas) return;

  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: "high-performance" });
  } catch (e) {
    canvas.remove();
    return;
  }

  const NAVY = 0x0b1c3f;
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const isSmall = window.innerWidth < 760;
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, isSmall ? 1 : 1.5));
  renderer.outputEncoding = THREE.sRGBEncoding;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  // نحول الكحلي للمساحة اللونية الخطية عشان يطلع نفس كحلي الموقع بالضبط
  const navyLinear = new THREE.Color(0.0147, 0.0237, 0.068);
  renderer.setClearColor(navyLinear, 1);

  const scene = new THREE.Scene();
  scene.background = navyLinear;
  const camera = new THREE.PerspectiveCamera(30, 1, 0.1, 100);

  // انعكاسات واقعية على المعدن والزجاج
  // نستخدمها بس على المعدن والزجاج بقوة خفيفة، عشان الكيس يبقى غامق مثل الصورة
  let ENV = null;
  if (THREE.RoomEnvironment) {
    const pmrem = new THREE.PMREMGenerator(renderer);
    ENV = pmrem.fromScene(new THREE.RoomEnvironment(), 0.04).texture;
  }
  scene.add(new THREE.HemisphereLight(0x7d96d8, 0x050a18, 0.3));
  const key = new THREE.DirectionalLight(0xcfdcff, 0.22);
  key.position.set(5, 6, 6);
  scene.add(key);

  const pc = new THREE.Group();
  scene.add(pc);

  // ================= الخامات =================
  const timeU = { value: 0 };
  const animated = [];   // خامات تتحرك مع الوقت

  const frameMat = new THREE.MeshStandardMaterial({ color: 0x0a0c12, roughness: 0.38, metalness: 0.7, envMap: ENV, envMapIntensity: 0.18 });
  const darkMat = new THREE.MeshStandardMaterial({ color: 0x07090f, roughness: 0.7, metalness: 0.3 });
  const boardMat = new THREE.MeshStandardMaterial({ color: 0x0d1018, roughness: 0.6, metalness: 0.45 });
  const sinkMat = new THREE.MeshStandardMaterial({ color: 0x14171f, roughness: 0.32, metalness: 0.85, envMap: ENV, envMapIntensity: 0.22 });
  const gpuMat = new THREE.MeshStandardMaterial({ color: 0x1d2027, roughness: 0.3, metalness: 0.85, envMap: ENV, envMapIntensity: 0.45 });
  const glassMat = new THREE.MeshPhysicalMaterial({
    color: 0x9db4ff, metalness: 0, roughness: 0.04, transparent: true, opacity: 0.06,
    envMap: ENV, envMapIntensity: 0.35, depthWrite: false, side: THREE.DoubleSide,
  });

  // لون RGB يمشي حول الشكل (قوس قزح متحرك)
  const HSV = `
    vec3 hsv2rgb(vec3 c){ vec4 K=vec4(1.,2./3.,1./3.,3.); vec3 p=abs(fract(c.xxx+K.xyz)*6.-K.www);
      return c.z*mix(K.xxx,clamp(p-K.xxx,0.,1.),c.y); }`;

  function rgbMaterial(phase, intensity = 1.6, speed = 0.12) {
    const m = new THREE.ShaderMaterial({
      uniforms: { uTime: timeU, uPhase: { value: phase }, uI: { value: intensity }, uS: { value: speed } },
      vertexShader: `varying vec2 vP; void main(){ vP=position.xy; gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.); }`,
      fragmentShader: `${HSV} uniform float uTime,uPhase,uI,uS; varying vec2 vP;
        void main(){ float a=atan(vP.y,vP.x)/6.28318;
          vec3 c=hsv2rgb(vec3(fract(a+uTime*uS+uPhase),1.,1.));
          gl_FragColor=vec4(c*uI,1.); }`,
    });
    m.toneMapped = false;
    return m;
  }

  // شريط إضاءة بلون واحد يتغير مع الوقت
  function glowMaterial(phase, intensity = 1.2, sat = 0.95) {
    const m = new THREE.ShaderMaterial({
      uniforms: { uTime: timeU, uPhase: { value: phase }, uI: { value: intensity }, uSat: { value: sat } },
      vertexShader: `void main(){ gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.); }`,
      fragmentShader: `${HSV} uniform float uTime,uPhase,uI,uSat;
        void main(){ gl_FragColor=vec4(hsv2rgb(vec3(fract(uTime*0.08+uPhase),uSat,1.))*uI,1.); }`,
    });
    m.toneMapped = false;
    return m;
  }

  // وجه المروحة: ريش شفافة مضيئة + مرآة لانهائية + محور غامق
  function fanFaceMaterial(phase) {
    const m = new THREE.ShaderMaterial({
      uniforms: { uTime: timeU, uPhase: { value: phase }, uSpin: { value: 5 + Math.random() * 2 } },
      transparent: true,
      vertexShader: `varying vec2 vUv; void main(){ vUv=uv; gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.); }`,
      fragmentShader: `${HSV} uniform float uTime,uPhase,uSpin; varying vec2 vUv;
        float ring(float r,float c,float w){ return exp(-pow((r-c)/w,2.)); }
        void main(){
          vec2 p=(vUv-.5)*2.; float r=length(p); if(r>1.) discard;
          float a=atan(p.y,p.x);
          // ريش المروحة وهي تدور
          float blades=.55+.45*smoothstep(-.2,.9,sin(7.*(a-uTime*uSpin)+r*3.));
          vec3 cyan=mix(vec3(.02,.62,1.),vec3(.25,.3,1.),.35+.35*sin(uTime*.25+uPhase*6.28));
          float body=smoothstep(.98,.6,r)*smoothstep(.18,.42,r);
          vec3 col=cyan*body*blades*.95;
          // حلقة بيضاء قوية عند الحافة الداخلية
          col+=mix(cyan,vec3(1.),.35)*ring(r,.86,.06)*1.25;
          // المرآة اللانهائية: حلقات تصغر وتخفت للداخل
          for(int i=0;i<4;i++){ float fi=float(i); col+=cyan*ring(r,.3-fi*.045,.012)*(1.3-fi*.28); }
          col+=mix(cyan,vec3(1.),.6)*ring(r,.36,.018)*1.3;
          // المحور الغامق في النص
          col*=smoothstep(.1,.16,r);
          gl_FragColor=vec4(col,1.);
        }`,
    });
    m.toneMapped = false;
    return m;
  }

  // ================= أشكال مساعدة =================
  function roundedRectShape(w, h, r) {
    const s = new THREE.Shape(), x = -w / 2, y = -h / 2;
    s.moveTo(x + r, y);
    s.lineTo(x + w - r, y); s.quadraticCurveTo(x + w, y, x + w, y + r);
    s.lineTo(x + w, y + h - r); s.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
    s.lineTo(x + r, y + h); s.quadraticCurveTo(x, y + h, x, y + h - r);
    s.lineTo(x, y + r); s.quadraticCurveTo(x, y, x + r, y);
    return s;
  }

  function roundedBox(w, h, d, r, mat) {
    const g = new THREE.ExtrudeGeometry(roundedRectShape(w, h, Math.min(r, w / 2, h / 2)), {
      depth: d, bevelEnabled: true, bevelThickness: Math.min(r, d / 2) * 0.6,
      bevelSize: Math.min(r, d / 2) * 0.4, bevelSegments: 3, curveSegments: 8,
    });
    g.center();
    return new THREE.Mesh(g, mat);
  }

  function add(mesh, x, y, z, parent = pc) {
    mesh.position.set(x, y, z);
    parent.add(mesh);
    return mesh;
  }

  // ================= المروحة =================
  const FAN = 0.6;
  function fan(phase) {
    const g = new THREE.Group();
    // الإطار المربع بفتحة دائرية
    const shape = roundedRectShape(FAN, FAN, 0.07);
    const hole = new THREE.Path();
    hole.absarc(0, 0, FAN * 0.45, 0, Math.PI * 2, true);
    shape.holes.push(hole);
    const frame = new THREE.Mesh(new THREE.ExtrudeGeometry(shape, {
      depth: 0.09, bevelEnabled: true, bevelThickness: 0.01, bevelSize: 0.01, bevelSegments: 2, curveSegments: 24,
    }), frameMat);
    frame.position.z = -0.045;
    g.add(frame);
    // شريط RGB حول الإطار (مثل المراوح اللي في الصورة)
    const outer = roundedRectShape(FAN - 0.03, FAN - 0.03, 0.06);
    const innerHole = roundedRectShape(FAN - 0.075, FAN - 0.075, 0.045);
    outer.holes.push(innerHole);
    const strip = new THREE.Mesh(new THREE.ShapeGeometry(outer, 16), rgbMaterial(phase, 1.25));
    strip.position.z = 0.056;
    g.add(strip);
    const stripBack = strip.clone();
    stripBack.rotation.y = Math.PI;
    stripBack.position.z = -0.056;
    g.add(stripBack);
    // الريش والمرآة
    const face = new THREE.Mesh(new THREE.CircleGeometry(FAN * 0.45, 64), fanFaceMaterial(phase));
    face.position.z = 0.01;
    g.add(face);
    const faceBack = face.clone();
    faceBack.rotation.y = Math.PI;
    faceBack.position.z = -0.01;
    g.add(faceBack);
    return g;
  }

  // ================= الكيس =================
  // x: من الخلف للأمام، y: الارتفاع، z: من اللوحة الأم للزجاج الجانبي
  const L = 2.7, H = 2.35, D = 1.55;
  const T = 0.05; // سماكة الإطار

  add(roundedBox(L + 0.1, 0.09, D + 0.1, 0.03, frameMat), 0, H / 2 + 0.02, 0);            // السقف
  add(roundedBox(L + 0.1, 0.12, D + 0.1, 0.03, frameMat), 0, -H / 2 - 0.03, 0);           // القاعدة
  add(roundedBox(0.08, H, D, 0.02, frameMat), -L / 2 - 0.02, 0, 0);                         // اللوح الخلفي
  add(new THREE.Mesh(new THREE.BoxGeometry(L, H, 0.02), darkMat), 0, 0, -D / 2 + 0.01);    // ورا اللوحة الأم
  // إطار الزاوية الأمامية (رفيع، بدون عمود)
  add(roundedBox(0.035, H, 0.035, 0.012, frameMat), L / 2, 0, D / 2);
  add(roundedBox(L, 0.035, 0.035, 0.012, frameMat), 0, H / 2 - 0.04, D / 2);
  add(roundedBox(L, 0.035, 0.035, 0.012, frameMat), 0, -H / 2 + 0.03, D / 2);
  add(roundedBox(0.035, 0.035, D, 0.012, frameMat), L / 2, H / 2 - 0.04, 0);
  add(roundedBox(0.035, 0.035, D, 0.012, frameMat), L / 2, -H / 2 + 0.03, 0);
  // الزجاج
  add(new THREE.Mesh(new THREE.PlaneGeometry(L, H - 0.06), glassMat), 0, 0, D / 2);
  const front = add(new THREE.Mesh(new THREE.PlaneGeometry(D, H - 0.06), glassMat), L / 2, 0, 0);
  front.rotation.y = Math.PI / 2;
  // رجول
  [[-1.1, -0.55], [1.1, -0.55], [-1.1, 0.55], [1.1, 0.55]].forEach(([x, z]) =>
    add(roundedBox(0.22, 0.07, 0.22, 0.03, frameMat), x, -H / 2 - 0.12, z));

  // ================= اللوحة الأم =================
  const MBZ = -D / 2 + 0.06;
  add(roundedBox(1.55, 1.75, 0.04, 0.02, boardMat), -0.42, 0.18, MBZ);
  add(roundedBox(0.75, 0.22, 0.12, 0.03, sinkMat), -0.6, 0.86, MBZ + 0.07);     // تبريد الباور فوق
  add(roundedBox(0.2, 0.75, 0.12, 0.03, sinkMat), -1.0, 0.48, MBZ + 0.07);      // تبريد الباور الجانبي
  add(roundedBox(0.5, 0.42, 0.06, 0.03, sinkMat), -0.62, -0.62, MBZ + 0.05);   // غطاء الأقراص
  add(roundedBox(0.36, 0.3, 0.07, 0.03, sinkMat), 0.05, -0.62, MBZ + 0.05);    // الشيبست
  // خطوط إضاءة خفيفة على اللوحة
  add(new THREE.Mesh(new THREE.BoxGeometry(0.6, 0.01, 0.01), glowMaterial(0.55, 1.2)), -0.62, -0.4, MBZ + 0.09);

  // ================= الرامات البيضاء =================
  const ramBody = new THREE.MeshStandardMaterial({ color: 0x8e95a3, roughness: 0.4, metalness: 0.5, envMap: ENV, envMapIntensity: 0.25 });
  const ramTop = new THREE.MeshBasicMaterial({ color: new THREE.Color(1.3, 1.4, 1.6) });
  ramTop.toneMapped = false;
  [0, 1].forEach(i => {
    const x = 0.02 + i * 0.1;
    add(roundedBox(0.05, 0.62, 0.17, 0.01, ramBody), x, 0.38, MBZ + 0.11);
    add(roundedBox(0.052, 0.07, 0.17, 0.01, ramTop), x, 0.72, MBZ + 0.11);
  });

  // ================= المبرد المائي =================
  const PUMP = new THREE.Vector3(-0.48, 0.36, MBZ + 0.13);
  const pump = new THREE.Group();
  pump.position.copy(PUMP);
  pc.add(pump);
  const pumpBody = new THREE.Mesh(new THREE.CylinderGeometry(0.22, 0.23, 0.16, 48), frameMat);
  pumpBody.rotation.x = Math.PI / 2;
  pump.add(pumpBody);
  // دوامة ألوان على غطاء المضخة
  const swirl = new THREE.ShaderMaterial({
    uniforms: { uTime: timeU },
    vertexShader: `varying vec2 vUv; void main(){ vUv=uv; gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.); }`,
    fragmentShader: `${HSV} uniform float uTime; varying vec2 vUv;
      void main(){ vec2 p=(vUv-.5)*2.; float r=length(p); float a=atan(p.y,p.x);
        float sw=a/6.28318+r*.55-uTime*.12;
        vec3 c=hsv2rgb(vec3(fract(sw),.65,1.));
        c=mix(c,vec3(1.),smoothstep(.35,0.,r)*.35);
        float edge=smoothstep(1.,.93,r);
        gl_FragColor=vec4(c*1.1*edge,1.); }`,
  });
  swirl.toneMapped = false;
  const cap = new THREE.Mesh(new THREE.CircleGeometry(0.2, 64), swirl);
  cap.position.z = 0.081;
  pump.add(cap);
  const capGlass = new THREE.Mesh(new THREE.SphereGeometry(0.2, 48, 16, 0, Math.PI * 2, 0, 0.5),
    new THREE.MeshPhysicalMaterial({ color: 0xffffff, roughness: 0.02, transparent: true, opacity: 0.12, envMap: ENV, envMapIntensity: 0.6 }));
  capGlass.rotation.x = Math.PI / 2;
  capGlass.position.z = 0.0;
  pump.add(capGlass);

  // الردياتير فوق + ٣ مراوح
  add(roundedBox(2.0, 0.08, 0.66, 0.02, sinkMat), 0.12, H / 2 - 0.08, 0.15);
  for (let i = 0; i < 3; i++) {
    const f = fan(0.1 + i * 0.12);
    f.rotation.x = Math.PI / 2;
    add(f, -0.53 + i * 0.65, H / 2 - 0.18, 0.15);
  }

  // الخراطيم المغلفة (شكلها مضفور)
  const braid = (() => {
    const c = document.createElement("canvas");
    c.width = 64; c.height = 64;
    const x = c.getContext("2d");
    x.fillStyle = "#0b0d12"; x.fillRect(0, 0, 64, 64);
    x.strokeStyle = "#2a2f3c"; x.lineWidth = 3;
    for (let i = -64; i < 128; i += 8) {
      x.beginPath(); x.moveTo(i, 0); x.lineTo(i + 64, 64); x.stroke();
      x.beginPath(); x.moveTo(i + 64, 0); x.lineTo(i, 64); x.stroke();
    }
    const t = new THREE.CanvasTexture(c);
    t.wrapS = t.wrapT = THREE.RepeatWrapping;
    t.repeat.set(30, 1);
    return t;
  })();
  const hoseMat = new THREE.MeshStandardMaterial({ map: braid, bumpMap: braid, bumpScale: 0.01, roughness: 0.75, metalness: 0.2 });
  [-0.06, 0.06].forEach((o, i) => {
    const curve = new THREE.CatmullRomCurve3([
      new THREE.Vector3(PUMP.x + 0.12, PUMP.y + o, PUMP.z + 0.05),
      new THREE.Vector3(PUMP.x + 0.55, PUMP.y + 0.05 + o, PUMP.z + 0.45),
      new THREE.Vector3(0.6 + i * 0.1, 0.55, 0.55),
      new THREE.Vector3(0.95 + i * 0.12, 0.95, 0.35),
      new THREE.Vector3(1.05 + i * 0.12, H / 2 - 0.14, 0.2),
    ]);
    pc.add(new THREE.Mesh(new THREE.TubeGeometry(curve, 80, 0.042, 14, false), hoseMat));
  });

  // ================= كرت الشاشة (أفقي) =================
  const gpu = new THREE.Group();
  gpu.position.set(-0.32, -0.32, MBZ + 0.38);
  pc.add(gpu);
  gpu.add(roundedBox(1.75, 0.2, 0.62, 0.04, gpuMat));                          // الجسم
  const back = add(roundedBox(1.75, 0.025, 0.62, 0.01, new THREE.MeshStandardMaterial({
    color: 0x1a1d24, roughness: 0.25, metalness: 0.95, envMap: ENV, envMapIntensity: 0.25 })), 0, 0.115, 0, gpu);  // الباك بليت
  back.castShadow = false;
  // تفاصيل الغطاء المائلة على الجنب
  for (let i = 0; i < 6; i++) {
    const fin = add(new THREE.Mesh(new THREE.BoxGeometry(0.05, 0.12, 0.012), sinkMat), -0.15 + i * 0.075, 0.0, 0.313, gpu);
    fin.rotation.z = 0.5;
  }
  add(new THREE.Mesh(new THREE.BoxGeometry(1.5, 0.014, 0.012), glowMaterial(0.6, 1.8, 0.55)), 0, -0.09, 0.315, gpu); // شريط إضاءة
  add(roundedBox(0.09, 0.07, 0.36, 0.01, sinkMat), 0.92, 0.0, 0, gpu);
  const gpuLight = new THREE.MeshBasicMaterial({ color: new THREE.Color(1.1, 1.15, 1.25) });
  gpuLight.toneMapped = false;
  add(new THREE.Mesh(new THREE.BoxGeometry(0.55, 0.012, 0.01), gpuLight), 0.35, 0.06, 0.316, gpu);
  add(new THREE.Mesh(new THREE.BoxGeometry(0.3, 0.012, 0.01), gpuLight), -0.55, 0.06, 0.316, gpu);
  // ضوء خفيف يوضح الكرت
  const gpuSpot = new THREE.PointLight(0x9ab8ff, 0.5, 1.6, 2);
  gpuSpot.position.set(0, 0.6, 0.8);
  gpu.add(gpuSpot);         // طرف الكرت
  // كيبلات الباور
  const cableMat = new THREE.MeshStandardMaterial({ color: 0x0a0b0f, roughness: 0.55, metalness: 0.2 });
  for (let i = 0; i < 8; i++) {
    const zz = -0.12 + i * 0.03;
    const curve = new THREE.CatmullRomCurve3([
      new THREE.Vector3(0.25, 0.12, zz),
      new THREE.Vector3(0.4, 0.38, zz + 0.05),
      new THREE.Vector3(0.62, 0.42, -0.22 + i * 0.012),
      new THREE.Vector3(0.78, 0.25, -0.36),
    ]);
    gpu.add(new THREE.Mesh(new THREE.TubeGeometry(curve, 24, 0.014, 6, false), cableMat));
  }

  // ================= المراوح الأمامية والخلفية والسفلية =================
  for (let i = 0; i < 3; i++) {
    const f = fan(0.45 + i * 0.1);
    f.rotation.y = -Math.PI / 2;
    add(f, L / 2 - 0.12, 0.66 - i * 0.66, 0.05);
  }
  const rear = fan(0.85);
  rear.rotation.y = Math.PI / 2;
  add(rear, -L / 2 + 0.07, 0.56, -0.05);
  for (let i = 0; i < 3; i++) {
    const f = fan(0.3 + i * 0.1);
    f.rotation.x = -Math.PI / 2;
    add(f, -0.72 + i * 0.66, -H / 2 + 0.1, 0.18);
  }
  // شرائط RGB صغيرة جنب المراوح الأمامية (مثل الصورة)
  for (let i = 0; i < 3; i++)
    add(new THREE.Mesh(new THREE.BoxGeometry(0.02, 0.5, 0.03), glowMaterial(0.15 + i * 0.1, 1.6)), L / 2 - 0.05, 0.66 - i * 0.66, 0.42);

  // ================= أضواء داخلية تنعكس على المعدن =================
  const inner = [
    { l: new THREE.PointLight(0x55ccff, 0.9, 2.6, 2), p: [0.2, 0.4, 0.3], ph: 0.55 },
    { l: new THREE.PointLight(0xaa66ff, 0.7, 2.4, 2), p: [-0.8, -0.5, 0.3], ph: 0.8 },
    { l: new THREE.PointLight(0x44ffcc, 0.6, 2.2, 2), p: [1.0, -0.2, 0.2], ph: 0.35 },
  ];
  inner.forEach(o => { o.l.position.set(...o.p); pc.add(o.l); });

  // توهج تحت الكيس
  const gc = document.createElement("canvas");
  gc.width = gc.height = 128;
  const gx = gc.getContext("2d");
  const grad = gx.createRadialGradient(64, 64, 0, 64, 64, 64);
  grad.addColorStop(0, "rgba(120,160,255,0.85)");
  grad.addColorStop(1, "rgba(120,160,255,0)");
  gx.fillStyle = grad;
  gx.fillRect(0, 0, 128, 128);
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(5, 3.4), new THREE.MeshBasicMaterial({
    map: new THREE.CanvasTexture(gc), transparent: true, blending: THREE.AdditiveBlending, depthWrite: false, opacity: 0.22,
  }));
  floor.rotation.x = -Math.PI / 2;
  floor.position.y = -H / 2 - 0.16;
  pc.add(floor);

  pc.scale.setScalar(0.9);

  // ================= التوهج (Bloom) =================
  let composer = null;
  const canBloom = THREE.EffectComposer && THREE.RenderPass && THREE.UnrealBloomPass;
  if (canBloom) {
    composer = new THREE.EffectComposer(renderer);
    composer.addPass(new THREE.RenderPass(scene, camera));
    const bloom = new THREE.UnrealBloomPass(new THREE.Vector2(256, 256), isSmall ? 0.7 : 0.95, 0.5, 0.72);
    composer.addPass(bloom);
    composer._bloom = bloom;
  }

  // ================= المقاس والكاميرا =================
  function resize() {
    const w = window.innerWidth, h = window.innerHeight;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    if (camera.aspect > 1.25) {
      camera.setViewOffset(w, h, w * 0.24, 0, w, h);   // على الشاشة العريضة: يسار
      camera.position.set(3.5, -0.25, 6.4);
    } else {
      camera.clearViewOffset();
      camera.position.set(3.6, -0.15, 6.6 / Math.max(camera.aspect, 0.5) * 0.7);
    }
    camera.lookAt(0, 0.12, 0);
    camera.updateProjectionMatrix();
    if (composer) {
      composer.setPixelRatio(renderer.getPixelRatio());
      composer.setSize(w, h);
      // التوهج بنص الدقة عشان يكون خفيف على الجهاز
      composer._bloom.resolution.set(w / 2, h / 2);
    }
  }
  window.addEventListener("resize", resize);
  resize();

  // ================= الحركة =================
  let mx = 0, my = 0, tx = 0, ty = 0;
  window.addEventListener("pointermove", e => {
    tx = e.clientX / window.innerWidth - 0.5;
    ty = e.clientY / window.innerHeight - 0.5;
  }, { passive: true });

  const tmp = new THREE.Color();
  function tick(t) {
    timeU.value = t;
    for (const o of inner) {
      tmp.setHSL((t * 0.08 + o.ph) % 1, 0.8, 0.6);
      o.l.color.copy(tmp);
    }
  }
  function draw() { composer ? composer.render() : renderer.render(scene, camera); }

  let last = performance.now(), t = 0, running = true;
  function frame(now) {
    if (!running) return;
    const dt = Math.min((now - last) / 1000, 0.05);
    last = now;
    t += dt;
    mx += (tx - mx) * 0.04;
    my += (ty - my) * 0.04;
    pc.rotation.y = -0.42 + Math.sin(t * 0.16) * 0.22 + mx * 0.3;
    pc.rotation.x = my * 0.08;
    pc.position.y = Math.sin(t * 0.55) * 0.03;
    tick(t);
    draw();
    requestAnimationFrame(frame);
  }

  if (reduceMotion) {
    pc.rotation.y = -0.42;
    tick(3);
    draw();
  } else {
    requestAnimationFrame(frame);
    document.addEventListener("visibilitychange", () => {
      running = !document.hidden;
      if (running) { last = performance.now(); requestAnimationFrame(frame); }
    });
  }

  // ================= الوضوح حسب التمرير =================
  // واضح فوق في الواجهة، ويخف لما تنزل للقطع عشان ما يشتت
  function fade() {
    const small = window.innerWidth < 980;
    // غيّر هالأرقام لو تبيه أوضح أو أخف (من ٠ إلى ١)
    const top = small ? 0.38 : 0.9, bottom = small ? 0.18 : 0.28;
    const k = Math.min(window.scrollY / (window.innerHeight * 0.8), 1);
    canvas.style.opacity = (top + (bottom - top) * k).toFixed(3);
  }
  window.addEventListener("scroll", fade, { passive: true });
  window.addEventListener("resize", fade);
  requestAnimationFrame(() => { canvas.classList.add("on"); fade(); });
})();
