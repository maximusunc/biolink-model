"""
Datamodel for metamodel

See datamodel.py for pure (autogenerated) data access objects

This module provides an OO facade for accessing these
"""

from enum import Enum
import logging
from .metamodel import *
from metamodel.metaschema import SchemaDefinitionSchema
import yaml

class NameStyle(Enum):
    """
    Different systems have different name conventions.

    E.g. in most programming languages classes are CamelCase

    in some, property names are underscore separated.
    """
    CAMELCASE = 1
    UNDERSCORE = 2
    NATURAL = 3
    LCAMELCASE = 4

class Manager(object):
    """
    Facade object for working with schemas
    """
    def __init__(self, schema=None):
        """
        initialize

        Arguments
        ---------
        - schema : SchemaDefinition
        """
        if schema is not None:
            self.schema = schema
        self.unreferenced = set()

    def load_schema(self, file, depth=0):
        """
        loads a schema from a file
        """
        logging.info('LOADING: {}'.format(file))
        obj = yaml.load(file)
        schemadef = SchemaDefinitionSchema()
        errs = schemadef.validate(obj)
        if len(errs) > 0:
            logging.error("CONFIG ERRS: {}".format(errs))
        schema = schemadef.load(obj).data
        logging.info('LOADING IMPORTS FOR {}'.format(schema.name))
        self.load_imports(schema, depth)
        if depth == 0:
            self.schema = schema
            logging.info('APPLYING EXTENSIONS')
            self.apply_extensions(schema)
        return schema

    def load_imports(self, schema, depth):
        """
        Imports are specified with the extend field
        """
        logging.info('Sc: {}'.format(schema.name))
        if schema.imports:
            for m in schema.imports:
                logging.info('IMPORTING: {}'.format(m))
                file = open(m + '.yaml', 'r')
                s2 = self.load_schema(file, depth+1)
                file.close()
                self.merge_schemas(schema, s2)

    def merge_schemas(self, s1, s2):
        if s2.classes:
            if s1.classes is None:
                s1.classes = []
            s1.classes += s2.classes
        if s2.slots:
            if s1.slots is None:
                s1.slots = []
            s1.slots += s2.slots
        if s2.types:
            if s1.types is None:
                s1.types = []
            s1.types += s2.types
                     
    def apply_extensions(self, schema):
        """
        Auto-apply 'reverse-isas'
        """
        for c in schema.classes:
            c = self.classdef(c)
            if c.apply_to:
                tc = self.classdef(c.apply_to)
                if tc:
                    if tc.mixins is None:
                        tc.mixins = []
                    logging.info("Applying '{}' to '{}'".format(c.name, tc.name))
                    tc.mixins.append(c.name)
        

    def get_name(self, n, style):
        if style == NameStyle.UNDERSCORE:
            return n.replace(" ","_")
        if style == NameStyle.CAMELCASE:
            return n.title().replace(" ","")
        if style == NameStyle.LCAMELCASE:
            s = n.title().replace(" ","")
            return s[0].lower() + s[1:]
        return n

        
    def slotdef(self, sn, c=None):
        """
        lookup a slot in the schema by name

        Returns
        -------
        SlotDefinition
        """
        assert( sn is not None )
        if isinstance(sn,SlotDefinition):
            return sn
        for s in self.schema.slots:
            if s.name == sn:
                return s

        # if not found, can use local definition
        if c is not None and c.slot_usage is not None:
            for s in c.slot_usage:
                if s.name == sn:
                    return s
        if sn not in self.unreferenced:
            logging.warning("No such slot: {} from class {}".format(sn, c))
            self.unreferenced.add(sn)

    def slot_name(self, s, style=NameStyle.UNDERSCORE):
        """
        Get the name of a slot using appropriate style

        Arguments
        ---------
        - s : SlotDefinition or string
        - style: NameStyle

        Returns
        -------
        string
        """
        # ensure an object
        slot = self.slotdef(s)
        return self.get_name(slot.name, style)

    def classdef(self, cn):
        """
        lookup a class in the schema by name

        Returns
        -------
        ClassDefinition
        """
        if isinstance(cn,ClassDefinition):
            return cn
        for c in self.schema.classes:
            if c.name == cn:
                return c
        if cn not in self.unreferenced:
            logging.warning("No such class: {}".format(cn))
            self.unreferenced.add(cn)


    def class_name(self, c, style=NameStyle.CAMELCASE):
        """
        Get the name of a class using appropriate style

        Arguments
        ---------
        - s : ClassDefinition or string
        - style: NameStyle

        Returns
        -------
        string
        """
        # ensure an object
        cls = self.classdef(c)
        if cls is None:
            raise ValueError("No cls for {}".format(c))
        return self.get_name(cls.name, style)

    def obj_name(self, obj):
        if isinstance(obj, ClassDefinition):
            return self.class_name(obj)
        else:
            return self.slot_name(obj)
    
    def obj_uri(self, obj):
        return "http://bioentity.io/vocab/{}".format(self.obj_name(obj))
    
    
    def child_nodes(self, obj):
        nodes = [c for c in self.schema.classes
                 if c.is_a is not None and c.is_a==obj.name]
        return nodes

    def child_nodes_by_mixin(self, obj):
        nodes = [c for c in self.schema.classes
                 if c.mixins is not None and obj.name in c.mixins]
        return nodes

    # returns pairs (cls, refCls) if cls references obj via refCls
    def all_class_usages(self, obj):
        pairs = []
        for c in self.schema.classes:
            rc =  self.get_class_usage_of(c, obj)
            if rc is not None:
                pairs.append((c, rc))
        return pairs

    # if a reference class rc directly or indirectly refers to obj in class c, return rc
    def get_class_usage_of(self, c, obj):
        c = self.classdef(c)
        slots = self.class_slotdefs(c, True, True)
        for s in slots:
            s = self.slotdef(s, c)
            r = self.class_slot_range(c, s)
            if r and self.classdef(r):
                r = self.classdef(r)
                if r.name == obj.name:
                    return r
                for a in self.ancestors(r, use_mixins=True, reflexive=False):
                    if a.name == obj.name:
                        return r
        return None

    # this is more expensive than using sets, but preserves order;
    # may be worth using an explicit orderedDicts lib, see https://stackoverflow.com/questions/1653970/does-python-have-an-ordered-set
    def remove_dupe_objs(self, objs):
        r = []
        visited = {}
        for obj in objs:
            if obj.name not in visited:
                visited[obj.name] = True
                r.append(obj)
        return r
    
    def ancestors(self, obj, use_mixins=False, reflexive=True, is_slot=False, use_isa=True, visited=[]):
        if isinstance(obj,str):
            if is_slot:
                obj = self.slotdef(obj)
            else:
                obj = self.classdef(obj)

        if obj.name in visited:
            raise ValueError("CYCLE: {} + {}".format(obj.name, visited))

        v2 = list(visited) + [obj.name]
        ancs = []
        if reflexive:
            ancs.append(obj)
        if obj.is_a and use_isa:
            ancs += self.ancestors(obj.is_a, use_mixins=use_mixins, reflexive=True, is_slot=is_slot, visited=v2)
        if obj.mixins and use_mixins:
            for m in obj.mixins:
                ancs += self.ancestors(m, use_mixins=use_mixins, reflexive=True, is_slot=is_slot, visited=v2)
        #return list(set(ancs))
        return self.remove_dupe_objs(ancs)
    
    def class_slotdefs(self, c, use_isa=True, use_mixins=False):
        """
        get all slots applicable for a class
        """
        # ensure an object
        cls = self.classdef(c)
        slots = []
        for a in self.ancestors(c, use_mixins=use_mixins, use_isa=use_isa):
            if a.slots is not None:
                for s in a.slots:
                    slots.append(s)
        return slots

    def class_slotdef_inherited_from(self, c, s):
        """
        Return the class from which a slotdef in a class is inherited from
        """
        # ensure an object
        cls = self.classdef(c)
        for a in self.ancestors(c, use_mixins=True, use_isa=True):
            if a.slots is not None:
                for s1 in a.slots:
                    if s.name == s1:
                        return a
        return None
    
    def class_slot_range(self, c, s):
        """
        Find the range of a slot when that slot is used in the context of a given class.

        Arguments can be either names or instances of SlotDefinition/ClassDefinition classes
        """
        return self.class_slot_getattr(c, s, 'range', defaultval=None)
    
    def class_slot_multivalued(self, c, s):
        """
        Find if a slot is multivalued
        """
        return self.class_slot_getattr(c, s, 'multivalued', defaultval=False)

    def class_slot_getattr(self, c, s, attr, defaultval=None):
        """
        Lookup an object attribute of a slot using inheritance
        """
        c = self.classdef(c)
        s = self.slotdef(s, c)

        # class-specific usage takes priority
        if c is not None and c.slot_usage is not None:
            for su in c.slot_usage:
                try:
                    if su.name == s.name and su.__getattribute__(attr) is not None:
                        return su.__getattribute__(attr)
                except AttributeError:
                    pass

        # general multivalued for slot
        try:
            if s.__getattribute__(attr):
                return s.__getattribute__(attr)
        except AttributeError:
            pass
        

        # inheritance up class mixins
        if c.mixins:
            for m in c.mixins:
                v = self.class_slot_getattr(m, s, attr, defaultval=defaultval)
                if v is not None:
                    return v
        
        # inheritance up slot mixins
        if s.mixins:
            for m in s.mixins:
                v = self.class_slot_getattr(c, m, attr, defaultval=defaultval)
                if v is not None:
                    return v
                
        # inheritance up class hierarchy
        if c.is_a:
            v = self.class_slot_getattr(c.is_a, s, attr, defaultval=defaultval)
            if v is not None:
                return v
        
        # inheritance up slot hierarchy
        if s.is_a:
            v = self.class_slot_getattr(c, s.is_a, attr, defaultval=defaultval)
            if v is not None:
                return v
        
        return defaultval
    
