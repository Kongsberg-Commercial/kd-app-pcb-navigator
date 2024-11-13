import FreeCADGui as Gui

from PySide2.QtCore import QThread
from PySide2.QtCore import Signal, Slot

from PySide2.QtWidgets import QTreeWidgetItem

import socket
import os
import PySide2
import configparser
import glob
import subprocess
import shutil
from pathlib import Path
from datetime import datetime
from pivy import coin

class FreeCADtest:
  def __init__(self):
    self.components = {}
    self.testpoints = {}
    self.pictures = []
    self.picture_index = -1
    self.path = {}
    self.test_folder = None
    self._test_info_dirty = False
    self._comp_tp_info_dirty = False
    self._picture_info_dirty = False
    self.teststeps_path = None
    
    self.current_selection = None
    self.current_folder = None
    self.current_components = {}
    self.current_testpoints = {}
    
    self.model = {}


    # load UI
    self.script_path = os.path.split(__file__)[0]
    ui_file = os.path.join(self.script_path,"navigator.ui")
    self.form = Gui.PySideUic.loadUi(ui_file)
    self.form.setWindowTitle("Rework helper")


    # get settings from registry
    programbase = 'pcb_navigator'
    self.settings = PySide2.QtCore.QSettings('KD', programbase)

    if self.settings.value("products_path") != None:
      self.log('Found settings in registry')
      self.products_path = self.settings.value("products_path")
    else:
      self.log('No settings in registry')
      self.products_path = os.path.join(self.script_path,"products")
    
    self.log(self.products_path)

    
    # connect signals
    self.form.cb_product.currentTextChanged.connect(self.on_product_changed)
    self.form.cb_test.currentTextChanged.connect(self.on_test_changed)

    self.form.tw_components.itemExpanded.connect(self.on_page_expanded)
    self.form.tw_components.itemClicked.connect(self.on_component_clicked)

    self.form.tw_testpoints.itemClicked.connect(self.on_tp_clicked)

    self.form.pb_next.clicked.connect(lambda : self.on_change_picture())
    self.form.pb_prev.clicked.connect(lambda : self.on_change_picture(-1))

    self.form.pb_save.clicked.connect(self.on_pb_save)
    self.form.pb_browse.clicked.connect(self.on_pb_browse)
    self.form.pb_open_folder.clicked.connect(self.on_pb_open_folder)
    self.form.pb_add_pictures.clicked.connect(self.on_pb_add_pictures)
    self.form.pb_add_test.clicked.connect(self.on_pb_add_test)
    self.form.pb_edit_test.clicked.connect(self.on_pb_edit_test)

    self.form.pb_flip.clicked.connect(self.on_pb_flip)
    self.form.pb_view_fit.clicked.connect(self.on_pb_view_fit)

    # initialize tree views
    self.form.tw_components.setColumnCount(2)
    self.form.tw_components.setHeaderLabels(["Page","notes"])

    self.form.tw_testpoints.setColumnCount(2)
    self.form.tw_testpoints.setHeaderLabels(["Page","notes"])


    # populate products
    self._clear_product()
    self._load_products()

    self.form.pb_prev.setEnabled(False)
    self.form.pb_next.setEnabled(False)

    self.form.te_test_info.textChanged.connect(self.on_test_info_changed)
    self.form.te_comp_tp_info.textChanged.connect(self.on_comp_tp_info_changed)
    self.form.te_picture_info.textChanged.connect(self.on_picture_info_changed)

    self.form.te_comp_tp_info.setEnabled(False)
    self.form.te_picture_info.setEnabled(False)


    # initi view
    Gui.SendMsgToActiveView("ViewFit")

    if Gui.activeDocument():
      Gui.activeDocument().activeView().viewTop()


  def log(self, msg):
    print(msg)

  def closeEvent(self, event):
    self.log('closeEvent')
    self.settings.setValue("products_path", self.products_path)

    PySide2.QtCore.QCoreApplication.exit()
  
  def on_product_changed(self):
    self.log('on_product_changed')
    
    self._clear_selection()
    
    product_name = self.form.cb_product.currentText()
    self._load_product(product_name)

  
  def on_test_changed(self):
    self.log('on_test_changed')

    # if anything changed in GUI
    self.save_information()
    
    self._clear_selection()

    test_name = self.form.cb_test.currentText()
    self.log('test name from GUI: %s'%test_name)
    if test_name:
      self._load_test(test_name)
  
  def on_component_clicked(self, item):
    item_name = item.text(0)
    self.log('on_component_clicked: %s'%item_name)
    
    self._refresh_current_item() # if folder manually deleted
    self.save_information()

    self.form.groupBox_3.setTitle('Information%s'%('       [%s]'%item_name if not item_name in self.components else ''))
    
    if item_name in self.components:
      page_name = item_name

      self._set_current_selection(None)

      for refdes in self.components[page_name]:
        self.add_selection(refdes)
    else:
      refdes = item_name
      self._update_information(item, force_enable=True)
      self.select(refdes)
      self._set_current_selection(('Components', refdes, item))
  
  def on_tp_clicked(self, item):
    item_name = item.text(0)
    self.log('on_tp_clicked: %s'%item_name)

    self._refresh_current_item() # if folder manually deleted
    self.save_information()

    self.form.groupBox_3.setTitle('Information%s'%('       [%s]'%item_name if not item_name in self.testpoints else ''))

    if self.form.pb_save.isEnabled():
      val = self._dlg_box('TP information changed','Save changes?')

      if val == PySide2.QtWidgets.QMessageBox.Yes:
          self.log("Yes!")
          self.save_information()
      else:
          self.log("No!")
    self.form.pb_save.setEnabled(False)
    
    if item_name not in self.testpoints: # ie.e not a page name
      refdes = item_name
      self._update_information(item, force_enable=True)
      self.select(refdes)      
      self._set_current_selection(('Testpoints', refdes, item))

    else:
      self._set_current_selection(None)

  
  def on_page_expanded(self, item):
    #PySide2.QtWidgets.Qtw_componentsItem
    self.log('on_page_expanded: %s'%item.text(0))

  def save_information(self, silent=False):
    if self._is_dirty() and not silent:
      choise = self._dlg_box('Information changed','Save changes?')

      if choise == PySide2.QtWidgets.QMessageBox.No:
          self.log("Abort save")
          return

    if self._test_info_dirty:
      readme_file_path = os.path.join(self.test_folder,"readme.txt")

      self.log('Save %s'%readme_file_path)
      self._save_to_file_and_backup(self.form.te_test_info, readme_file_path)

      self._test_info_dirty = False

    if self._comp_tp_info_dirty:
      readme_file_path = os.path.join(self.current_folder,"readme.txt")

      self.log('Save %s'%readme_file_path)
      self._save_to_file_and_backup(self.form.te_comp_tp_info, readme_file_path)

      self._comp_tp_info_dirty = False

    if self._picture_info_dirty:
      picture_path = self.pictures[self.picture_index][0]
      txt_path = os.path.splitext(picture_path)[0] + '.txt'
      
      self.log('Save %s'%txt_path)
      self._save_to_file_and_backup(self.form.te_picture_info, txt_path)

      self._picture_info_dirty = False

    self._refresh_current_item()

    self.form.pb_save.setEnabled(False)

  def on_pb_add_pictures(self, state):
    # if anything changed in GUI
    self.save_information()

    # infofolder missing?
    if not os.path.isdir(self.current_folder):
      refdes = self.current_selection[1]
      choise = self._dlg_box('No information-folder for current selection', 'Add folder for %s?'% refdes)
      if choise == PySide2.QtWidgets.QMessageBox.Yes:
        self._make_info_folder(self.current_folder)
      else:
        self.log("Make new folder canceled")
        return

    filters = "Images (*.png *.jpg)"
    filenames = PySide2.QtWidgets.QFileDialog.getOpenFileNames(self.form, "","", filters)[0]
    self.log(filenames)

    for src_file_path in filenames:
      # copy picture
      src_file_name = os.path.split(src_file_path)[1]
      dst_file_path = os.path.join(self.current_folder, src_file_name)
      shutil.copyfile(src_file_path, dst_file_path)

      # add empty picture description file
      info_file_name = os.path.splitext(src_file_name)[0] + '.txt'
      info_file_path = os.path.join(self.current_folder, info_file_name)
      with open(info_file_path, "w") as f:pass
    
    # update information for selected item
    self._update_information(self.current_selection[2])

    self._refresh_current_item()


  def on_pb_add_test(self, state):
    self.log('on_pb_add_test')

    # if anything changed in GUI
    self.save_information()

    product_name = self.form.cb_product.currentText()
    test_name, ok = PySide2.QtWidgets.QInputDialog.getText(self.form, 'text', 'Enter some text')
    self.log(test_name)
    if ok:
      new_test_folder = os.path.join(self.teststeps_path,test_name)
      if os.path.isdir(new_test_folder):
        self._msg_box('Test already exsist',test_name+' '*50)
      else:
        self.log('ok')
        self._make_test_folder(product_name, test_name)
        self._load_product(product_name)


  def on_pb_edit_test(self, state):
    self.log('on_pb_edit_test')

    # if anything changed in GUI
    self.save_information()

    test_name = self.form.cb_test.currentText()
    config_file = os.path.join(self.test_folder,"teststep.ini")
    if not os.path.isfile(config_file):
      self._msg_box('Config file not found',config_file)
      return
    
    p = subprocess.Popen(["notepad.exe", config_file])
    p.wait() # wait for editor to close
    self._load_test(test_name)
  
  def on_pb_open_folder(self, state):
    
    # if anything changed in GUI
    self.save_information()

    refdes = self.current_selection[1]
    self.log('on_pb_open_folder')
    if not os.path.isdir(self.current_folder):
      choise = self._dlg_box('No information for current selection', 'Add folder for %s?'% refdes)
      if choise == PySide2.QtWidgets.QMessageBox.Yes:
        self._make_info_folder(self.current_folder)
        self.save_information(silent=True)
        self._refresh_current_item()
        self._open_folder(self.current_folder)
      else:
        self.log("Make new folder canceled")
    else:
      self.save_information(silent=True)
      self._open_folder(self.current_folder)


  def on_pb_view_fit(self, state):
    self.log('on_pb_view_fit')
    Gui.SendMsgToActiveView("ViewFit")


  def on_pb_flip(self, state):
    self.log('on_pb_flip')
    #cam = Gui.ActiveDocument.ActiveView.getCameraNode()
    #cam_pos = cam.position.getValue().getValue()
    #cam.position.setValue(0,0,0)
    if state:
      Gui.activeDocument().activeView().viewBottom()
      #cam.orientation.setValue((1,0,0,0))
      self.form.pb_flip.setText('Bottom side')
    else:
      Gui.activeDocument().activeView().viewTop()
      #cam.orientation.setValue((0,0,0,1))
      #cam.orientation.setValue(coin.SbVec3f(0,0,1), 3.14)
      self.form.pb_flip.setText('Top side')
    #cam.position.setValue(cam_pos)

  def on_pb_browse(self, state):
    folder = PySide2.QtWidgets.QFileDialog.getExistingDirectory(None, "Select Folder")
    if folder:
      self.log(folder)
      self.products_path = folder
      self._clear_product()
      self._load_products()

  def on_pb_save(self, state):
    self.save_information()


  def on_change_picture(self, direction=1):
    self.save_information()
    self._next_picture(direction)

  def on_test_info_changed(self):
    self.log('on_test_info_changed')
    self._test_info_dirty = True
    self.form.pb_save.setEnabled(True)

  def on_comp_tp_info_changed(self):
    self.log('on_comp_tp_info_changed')
    self._comp_tp_info_dirty = True
    if self.current_selection:
      self.form.pb_save.setEnabled(True)

  def on_picture_info_changed(self):
    self.log('on_picture_info_changed')
    self._picture_info_dirty = True
    if self.current_selection:
      self.form.pb_save.setEnabled(True)

  def _parse_active_document(self):
        
    self.model = {}

    self.model['components'] = {}
    self.model['testpoints'] = {}
    self.model['symbols'] = {}

    components = FreeCAD.ActiveDocument.getObject('Components')
    placebounds = FreeCAD.ActiveDocument.getObject('PlaceBound')

    layers = ['Top', 'Bottom']

    for layer in layers:
      comps = components.getObject('Components%s'%layer)
      for name in comps.getSubObjects():
        obj_name = name.strip('.')
        obj = comps.getObject(obj_name)

        refdes = obj_name
        self.model['symbols'][refdes] = (obj, layer)

        if refdes.startswith('TP'):
          self.model['testpoints'][refdes] = (obj, layer)
        else:
          self.model['components'][refdes] = (obj, layer)

      placebound = placebounds.getObject('PlaceBound%s'%layer)
      for feaure_name in placebound.getSubObjects():
        obj = placebound.getObject(feaure_name.strip('.'))
        refdes = obj.Label[obj.Label.index('_')+1:]

        self.model['symbols'][refdes] = (obj, layer)
        self.model['testpoints'][refdes] = (obj, layer)

    self.log(self.model)


  def select(self, refdes):
    if not Gui.activeDocument():
      return
    
    Gui.Selection.clearSelection()

    self._parse_active_document()

    
    (obj, layer) = self.model['symbols'][refdes]

    Gui.Selection.addSelection(obj)
    obj_postition = obj.Shape.BoundBox.Center
    self.log(obj.Label)

    if self.form.cb_pan_selection.isChecked():
      cam = Gui.ActiveDocument.ActiveView.getCameraNode()
      cam.position.setValue(obj_postition)

    if self.form.cb_auto_flip.isChecked():
      self.log('switch to %s'%layer)
      self.form.pb_flip.setChecked(layer=='Bottom')
      self.on_pb_flip(layer=='Bottom')


  def add_selection(self, name):
    if not Gui.activeDocument():
      return
    
    for obj in FreeCAD.ActiveDocument.Objects:
      if obj.Label == name:
        Gui.Selection.addSelection(obj)
        break

  def _load_products(self):
    self.log(self.products_path)
    products = [folder for folder in os.listdir(self.products_path) if os.path.isfile(os.path.join(self.products_path, folder, 'components.txt'))]

    self.form.le_products_path.setText(self.products_path)
    self._clear_product()
    
    if len(products):
      self.form.cb_product.addItems(products)

      # HACK: can't trigger on closeEvent()
      # store settings in registry
      self.settings.setValue("products_path", self.products_path)

      self.form.gb_operation.setEnabled(True)
    else:
      self._msg_box('Warning', 'No valid product folders found')

  
  def _load_product(self, product_name):
    self.log('_load_product: %s'%product_name)

    # if anything changed in GUI
    self.save_information()

    if not product_name:
      return

    # get components per page
    prodfile = os.path.join(self.products_path, product_name, "components.txt")

    if os.path.isfile(prodfile):
      f = open(prodfile)
      lines = f.readlines()
      f.close()

      self.components = {}
      self.testpoints = {}

      for line in lines:
        line = line.strip()
        if line:
          if line.startswith('['):
            page = line[1:-1].lower()
            #self.log(page)
            self.components[page] = []
            self.testpoints[page] = []
          else:
            refdes = line
          # self.log(refdes)
            data = self.testpoints if refdes.startswith('TP') else self.components
            data[page].append(refdes)


      #self.testpoints_path = os.path.join(self.products_path,product_name,"testpoints")
      #self.components_path = os.path.join(self.products_path,product_name,"components")

      self.path["Testpoints"] = os.path.join(self.products_path,product_name,"testpoints")
      self.path["Components"] = os.path.join(self.products_path,product_name,"components")

      # get all teststeps
      self.teststeps_path = os.path.join(self.products_path,product_name,"teststeps")
      test_steps = [x for x in os.listdir(self.teststeps_path) if os.path.isdir(os.path.join(self.teststeps_path,x))]
      #self.log(test_steps)
    else:
      self.log('ERROR: not a valid product folder')

    self.form.cb_test.clear()
    self.form.cb_test.addItems(test_steps)


  def _load_test(self, test_name):
    self.current_selection = None

    # get components relevant for this test
    self.test_folder = os.path.join(self.teststeps_path,test_name)

    teststep_config = os.path.join(self.test_folder,'teststep.ini')
    config = configparser.ConfigParser()
    config.read(teststep_config)

    self._load_textedit_from_file( self.form.te_test_info, os.path.join(self.test_folder,'readme.txt'))

    self.current_components = {}
    self.current_testpoints = {}
    self.log(self.test_folder)
    for page in config['pages']:
      if config['pages'][page] == 'all':
        self.current_components[page] = self.components[page]
        self.current_testpoints[page] = self.testpoints[page]

    self._load_tws()


  def _clear_product(self):
    self._clear_selection()
    self.form.cb_product.clear()
    self.form.cb_test.clear()
    self.form.gb_operation.setEnabled(False)


  def _set_current_selection(self, selection):
    if selection:
      group = selection[0]
      refdes = selection[1]
      item = selection[2]
      self.current_selection = (group, refdes, item)
      self.current_folder = os.path.join(self.path[group], refdes)

      self.form.pb_open_folder.setEnabled(True)
      self.form.pb_add_pictures.setEnabled(True)

      # enable add picture only when folder exsist
      #if os.path.isdir(self.current_folder):
      #  self.form.pb_add_pictures.setEnabled(True)
      #else:
      #  self.form.pb_add_pictures.setEnabled(False)

    else:
      self._clear_selection()

    self._comp_tp_info_dirty = False
    self._picture_info_dirty = False


  def _clear_selection(self):
      Gui.Selection.clearSelection()

      self.form.groupBox_3.setTitle('Information')

      self._clear_widgets_blocked(
        [
          self.form.te_comp_tp_info,
          self.form.te_picture_info,
          self.form.picture
        ]
      )

      self.pictures = []
      self.current_folder = None
      self.current_selection = None

      self.form.pb_open_folder.setEnabled(False)
      self.form.pb_add_pictures.setEnabled(False)
      self.form.pb_next.setEnabled(False)
      self.form.pb_prev.setEnabled(False)
      self.form.pb_open_folder.setEnabled(False)
      self.form.pb_add_pictures.setEnabled(False)


  def _clear_widgets_blocked(self, widgets):
      for widget in widgets:
        block_state = widget.blockSignals(True)
        widget.clear()
        widget.blockSignals(block_state)


  def _make_test_folder(self, product_name, test_name):
    new_test_folder = os.path.join(self.teststeps_path,test_name)

    os.makedirs(new_test_folder)

    inc = 'all' if self.form.cb_inc_all.isChecked() else 'none'

    readme_file_path = os.path.join(new_test_folder,"readme.txt")
    with open(readme_file_path, "w") as f:
      f.write('%s components per pages included'%inc)
    
    pages = self._get_schematic_pages(product_name)
    config = configparser.ConfigParser()
    config['pages'] = {}.fromkeys(pages, inc)

    config_file = os.path.join(new_test_folder,"teststep.ini")
    with open(config_file, 'w') as config_file:
      config.write(config_file)

  def _make_info_folder(self, folder):
    # Make new folder and an empty readme file
    os.makedirs(folder)
    readme_file_path = os.path.join(folder,"readme.txt")
    with open(readme_file_path, "w") as f:pass

  def _open_folder(self, folder):
      os.startfile(folder)

  def _has_info(self):
    return os.path.isdir(self.current_folder)

  def _refresh_current_item(self):
    if self.current_selection:
      current_item = self.current_selection[2]
      item_note = current_item.text(1)

      # need to verify selection?
      # .isSelected()
      #
      # .setSelected(bool select)
      #

      #self.log('check info: %d %s'%(self._has_info(),item_note))
      if self._has_info() and item_note != 'YES':
        self.log('updating info column')
        current_item.setText(1, 'YES')
      elif not self._has_info() and item_note == 'YES':
        self.log('updating info column')
        current_item.setText(1, '')
      

  def _load_tws(self):
    self._load_tw(self.form.tw_components, self.current_components, self.path['Components'])
    self._load_tw(self.form.tw_testpoints, self.current_testpoints, self.path['Testpoints'])


  def _update_information(self, item, force_enable=False):
      self._update_text_edit(self.form.te_comp_tp_info, item, 'readme.txt',force_enable=force_enable)   
      self._set_pictures(item)
      self._next_picture() 


  def _set_pictures(self, item):
      refdes = item.text(0)
      
      # Test points or components?
      i = self.form.tw_comm.currentIndex()
      group = self.form.tw_comm.tabText(i)
      path = self.path[group]

      notes_path = os.path.join(path,refdes)
      self.pictures = []
      for file_types in ['*.png','*.jpg']:
        self.pictures.extend([(ppath, path, item) for ppath in glob.glob('%s/%s'%(notes_path, file_types))])
      if len(self.pictures) == 0:
        self.form.pb_prev.setEnabled(False)
        self.form.pb_next.setEnabled(False)

      self.picture_index = -1


  def _update_text_edit(self, widget, item, filename, force_enable=False):
      block_state = widget.blockSignals(True)
      refdes = item.text(0)
      item_note = item.text(1)
      
      # Test points or components?
      i = self.form.tw_comm.currentIndex()
      group = self.form.tw_comm.tabText(i)
      path = self.path[group]

      if item_note == 'YES':
        self.log('notes found for %s'%refdes)
        notes_path = os.path.join(path,refdes)
        txt_file_path = os.path.join(notes_path,filename)
        self._load_textedit_from_file(widget, txt_file_path, force_enable=force_enable)

      else:
        self.log('no notes found for %s'%refdes)
        widget.clear()
        widget.setEnabled(True if force_enable else False)
      widget.blockSignals(block_state)


  def _next_picture(self, direction=1):
    picture_widget = self.form.picture
    txt_widget = self.form.te_picture_info

    block_state = txt_widget.blockSignals(True)
    picture_widget.clear()
    txt_widget.clear()
    txt_widget.setEnabled(False)
    txt_widget.blockSignals(block_state)

    self.picture_index += direction
    if  self.picture_index <= 0 :
       self.picture_index = 0
       self.form.pb_prev.setEnabled(False)
    else:
      if len(self.pictures):
        self.form.pb_prev.setEnabled(True)
      else:
        self.form.pb_prev.setEnabled(False)


    if self.picture_index >= len(self.pictures)-1:
       self.picture_index = len(self.pictures)-1
       self.form.pb_next.setEnabled(False)
    else:
       self.form.pb_next.setEnabled(True)

    #self.log(self.picture_index)
    #self.log(self.pictures)

    if len(self.pictures):
      picture_path = self.pictures[self.picture_index][0]


      #picture_widget.setPixmap(PySide2.QtGui.QPixmap(os.path.realpath(picture_path)))
      pixmap =  PySide2.QtGui.QPixmap(picture_path)
      picture_widget.setPixmap(pixmap.scaledToHeight(self.form.picture.height()))

      
      txt_path = os.path.splitext(picture_path)[0] + '.txt'
      txt_folder = os.path.dirname(picture_path)
      item = self.pictures[self.picture_index][2]
      self.log(txt_folder)
      self.log(os.path.basename(txt_path))

      i = self.form.tw_comm.currentIndex()
      group = self.form.tw_comm.tabText(i)

      self._update_text_edit(txt_widget, item, os.path.basename(txt_path), force_enable=True)


  def _load_tw(self, widget, data, path):
    widget.clear()
    items = []

    for key, values in data.items():
        item = QTreeWidgetItem([key])
        for refdes in sorted(values):
            notes_path = os.path.join(path,refdes)
            
            note = 'YES' if os.path.isdir(notes_path) else ''
            child = QTreeWidgetItem([refdes, note])
            item.addChild(child)
        items.append(item)
    widget.insertTopLevelItems(0, items)


  def _load_textedit_from_file(self, widget, path, force_enable=False):
    block_state = widget.blockSignals(True)
    self.log('force enable: %d'%force_enable)
    self.log(path)
    if os.path.isfile(path):
      widget.setEnabled(True)
      with open(path) as f:
        text = ''
        for line in f.readlines():
          text += line
        widget.setPlainText(text)
    else:
      widget.clear()
      widget.setEnabled(True if force_enable else False)

    widget.blockSignals(block_state)


  def _get_schematic_pages(self, product_name):
    # get components per page
    prodfile = os.path.join(self.products_path, product_name,"components.txt")
    f = open(prodfile)
    lines = f.readlines()
    f.close()

    self.components = {}
    self.testpoints = {}

    pages = []
    for line in lines:
      line = line.strip()
      if line:
        if line.startswith('['):
          page = line[1:-1].lower()
          pages.append(page)
    return pages

  
  def _msg_box(self, title, text):
    dlg = PySide2.QtWidgets.QMessageBox(self.form)
    dlg.setWindowTitle(title)
    dlg.setText(text)
    dlg.setStandardButtons(PySide2.QtWidgets.QMessageBox.Ok)
    dlg.setIcon(PySide2.QtWidgets.QMessageBox.Question)
    return dlg.exec_()

  
  def _dlg_box(self, title, text):
    dlg = PySide2.QtWidgets.QMessageBox(self.form)
    dlg.setWindowTitle(title)
    dlg.setText(text)
    dlg.setStandardButtons(PySide2.QtWidgets.QMessageBox.Yes | PySide2.QtWidgets.QMessageBox.No)
    dlg.setIcon(PySide2.QtWidgets.QMessageBox.Question)
    return dlg.exec_()


  def _save_to_file_and_backup(self, widget, file_path):
    # https://stackoverflow.com/questions/25851314/making-a-backup-file-appending-date-time-moving-file-if-the-file-exists-pyt
    # rename origianl file
    filename = Path(os.path.basename(file_path))
    self.log(filename)

    target_directory = os.path.join(os.path.dirname(file_path),'bakcup')
    if not os.path.isdir(target_directory):
      os.makedirs(target_directory)
    target_directory = Path(target_directory)
    self.log(target_directory)
    
    # if file does not exsist, skip making backup
    if os.path.isfile(file_path):
      modified_time = os.path.getmtime(file_path)
      timestamp = datetime.fromtimestamp(modified_time).strftime("%b-%d-%Y_%H.%M.%S")
      target_file = target_directory / f'{filename.stem}_{timestamp}{filename.suffix}'
      #self.log(target_file)
      os.rename(file_path, target_file)

    # wire new file
    new_text = widget.toPlainText()
    self.log(new_text)
    with open(file_path, "w") as f:
      f.write(new_text)

  def _is_dirty(self):
    return self._test_info_dirty or  self._comp_tp_info_dirty or self._picture_info_dirty

Gui.Control.showDialog(FreeCADtest())